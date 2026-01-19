import os
import json
import boto3
import requests
import pandas as pd
from dotenv import load_dotenv
from groq import Groq
from pricing_tools import get_aws_price, get_azure_price, get_gcp_price 
from google.cloud import billing_v1

# =================================================
# ENV & CONFIG 
# =================================================
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found")

MODEL_NAME = "llama-3.1-8b-instant"
INPUT_CSV = "test.csv"
OUTPUT_CSV = "boq_output_tools.csv"

client = Groq(api_key=GROQ_API_KEY)

# =================================================
# FALLBACK PRICING (LAST RESORT)
# =================================================
FALLBACK_PRICES = {
    "AWS": {"t3.medium": 0.0416, "t2.micro": 0.0116},
    "AZURE": {"Standard_B1s": 0.012, "Standard_D2s_v3": 0.096},
    "GCP": {"e2-micro": 0.0076, "n1-standard-1": 0.0475}
}


# =================================================
# TOOL DEFINITIONS (LLM BINDING)
# =================================================
LLM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_aws_price",
            "description": "Get AWS EC2 on-demand hourly price",
            "parameters": {
                "type": "object",
                "properties": {
                    "instance_type": {"type": "string"},
                    "region_code": {"type": "string"}
                },
                "required": ["instance_type", "region_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_azure_price",
            "description": "Get Azure VM on-demand hourly price",
            "parameters": {
                "type": "object",
                "properties": {
                    "instance_type": {"type": "string"},
                    "region": {"type": "string"}
                },
                "required": ["instance_type", "region"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_gcp_price",
            "description": "Get GCP Compute Engine on-demand hourly price",
            "parameters": {
                "type": "object",
                "properties": {
                    "instance_type": {"type": "string"},
                    "region": {"type": "string"}
                },
                "required": ["instance_type", "region"]
            }
        }
    }
]

# =================================================
# TOOL EXECUTOR (YOU CONTROL EXECUTION)
# =================================================
def execute_tool(tool_name, args):
    if tool_name == "get_aws_price":
        return get_aws_price(
            args["instance_type"],
            args["region_code"]
        )

    if tool_name == "get_azure_price":
        return get_azure_price(
            args["instance_type"],
            args["region"]
        )

    if tool_name == "get_gcp_price":
        return get_gcp_price(
            args["instance_type"],
            args["region"]
        )

    raise ValueError(f"Unknown tool: {tool_name}")


# =================================================
# PRICE RESOLUTION (NO LLM CALCULATION)
# =================================================
def get_price_from_tools(provider, instance, region):
    provider = provider.upper()

    if provider == "AWS":
        return get_aws_price(instance, region), "AWS_API"

    elif provider == "AZURE":
        return get_azure_price(instance, region), "AZURE_API"

    elif provider == "GCP":
        return get_gcp_price(instance, region), "GCP_API"

    fallback = FALLBACK_PRICES.get(provider, {}).get(instance)
    if fallback:
        return fallback, "FALLBACK"

    return 0.05, "DEFAULT"

# =================================================
# LLM VERIFICATION WITH TOOL BINDING
# =================================================
def llm_verify_price(provider, instance, region, price):
    prompt = f"""
    Verify the following cloud pricing.

    Provider: {provider}
    Instance: {instance}
    Region: {region}
    Hourly Price USD: {price}

    Decide if the price is realistic for ON-DEMAND Linux compute.

    Return STRICT JSON:
    {{
      "is_valid": true | false,
      "confidence": "high" | "medium" | "low"
    }}
    """

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a pricing verifier. "
                    "You may call tools, but you must NEVER calculate prices."
                )
            },
            {"role": "user", "content": prompt}
        ],
        tools=LLM_TOOLS,
        tool_choice="auto",
        temperature=0
    )
    msg = response.choices[0].message

    if msg.tool_calls:
        tool_call = msg.tool_calls[0]
        tool_args = json.loads(tool_call.function.arguments)
        tool_result = execute_tool(tool_call.function.name, tool_args)
        follow_up = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict JSON API.\n"
                        "You MUST return ONLY a valid JSON object.\n"
                        "Do NOT include explanations, markdown, backticks, or text.\n"
                        "Do NOT repeat the input.\n"
                        "If you violate this, the response will be discarded."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        "Verify the cloud price below.\n\n"
                        f"Provider: {provider}\n"
                        f"Instance: {instance}\n"
                        f"Region: {region}\n"
                        f"Hourly Price USD: {price}\n\n"
                        "Rules:\n"
                        "- Do NOT calculate prices\n"
                        "- Use tool data only if needed\n"
                        "- Decide if the price is realistic\n\n"
                        "Return EXACTLY this JSON format:\n"
                        "{\"is_valid\": true|false, \"confidence\": \"high|medium|low\"}"
                    )
                },
                msg,
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"hourly_price": tool_result})
                }
            ],
            temperature=0,
            max_tokens=50
        )

        # print("follow_up ::", follow_up)
        result = json.loads(follow_up.choices[0].message.content)
        # print("result ::", result)
        return result.get("is_valid", True), result.get("confidence", "unknown")

    try:
        result = json.loads(msg.content)
        return result.get("is_valid", True), result.get("confidence", "unknown")
    except Exception:
        return True, "unknown"

# =================================================
# BOQ GENERATION
# =================================================
def generate_boq(Input_file_path, provider):
    ext = os.path.splitext(Input_file_path)[1].lower()

    if ext == ".csv":
        try:
            # Try UTF-8 first
            df = pd.read_csv(Input_file_path, encoding="utf-8")
        except UnicodeDecodeError:
            # Fallback encodings (very common in Windows CSVs)
            df = pd.read_csv(Input_file_path, encoding="latin1")
    elif ext in [".xls", ".xlsx"]:
        df = pd.read_excel(Input_file_path)
    else:
        raise ValueError("Unsupported file format. Please upload CSV or Excel.")

    rows = []
    total = 0.0

    for _, r in df.iterrows():
        # -----------------------------
        # Normalize inputs
        # -----------------------------
        provider = provider.upper()
        region = r["region"]
        instance_type = r["resource_type"]  # e.g. n1-standard-2, Standard_D2s_v3
        service_type = r.get("service_type", "").lower()

        # -----------------------------
        # Resolve usage
        # -----------------------------
        usage = r.get("UsageAmount")

        if pd.notna(usage) and float(usage) > 0:
            resolved_usage = float(usage)

        elif service_type in ["compute", "virtual_machine", "managed_database"]:
            resolved_usage = float(r.get("hours_per_month", 720))

        elif service_type in ["object_storage", "storage"]:
            resolved_usage = float(r.get("storage_gb", 0))

        elif service_type in ["network", "network_egress"]:
            resolved_usage = 0.0  # priced separately later

        else:
            resolved_usage = 720  # safe default for compute

        # -----------------------------
        # Get unit price
        # -----------------------------
        print("Resolving price →", provider, instance_type, region)

        unit_price, source = get_price_from_tools(
            provider=provider,
            instance=instance_type,
            region=region
        )

        if unit_price is None:
            unit_price = 0.0
            source = "NOT_FOUND"

        # -----------------------------
        # LLM verification (optional)
        # -----------------------------
        is_valid, confidence = llm_verify_price(
            provider=provider,
            instance=instance_type,
            region=region,
            price=unit_price
        )

        print("LLM verification →", is_valid, confidence)

        # -----------------------------
        # Monthly cost calculation
        # -----------------------------
        monthly_cost = round(unit_price * resolved_usage, 2)
        print(monthly_cost)
        total += monthly_cost
        print("total :",total)
        # -----------------------------
        # Append output row
        # -----------------------------
        rows.append({
            "Provider": provider,
            "Service Type": service_type,
            "Instance Type": instance_type,
            "Region": region,
            "Usage": resolved_usage,
            "Unit Price (USD/hr)": round(unit_price, 4),
            "Monthly Cost (USD)": monthly_cost,
            "Source": source,
            "LLM Verification": "OK" if is_valid else "FLAGGED",
            "Confidence": confidence
        })

    # -----------------------------
    # Total row
    # -----------------------------
    rows.append({
        "Provider": "TOTAL",
        "Service Type": "",
        "Instance Type": "",
        "Region": "",
        "Usage": "",
        "Unit Price (USD/hr)": "",
        "Monthly Cost (USD)": round(total, 2),
        "Source": "",
        "LLM Verification": "",
        "Confidence": ""
    })

    pd.DataFrame(rows).to_csv(OUTPUT_CSV, index=False)
    print(f"\n✅ BOQ generated → {OUTPUT_CSV}")


# =================================================
# ENTRY POINT
# =================================================
if __name__ == "__main__":
    provider = "Azure"
    Input_file_path = os.path.join(os.getcwd,'uploads','test.csv')
    generate_boq(Input_file_path, provider)
