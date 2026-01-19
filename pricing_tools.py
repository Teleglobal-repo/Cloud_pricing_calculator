import boto3
import json
import requests
from google.cloud import billing_v1


# =================================================
# PRICING TOOLS (AUTHORITATIVE)
# =================================================
def get_aws_price(instance_type, region_code):
    region_map = {
        "us-east-1": "US East (N. Virginia)",
        "us-west-2": "US West (Oregon)",
        "eu-west-1": "EU (Ireland)",
        "ap-south-1": "Asia Pacific (Mumbai)"
    }

    location = region_map.get(region_code)
    if not location:
        print(f"Unsupported region: {region_code}")
        return None

    client = boto3.client("pricing", region_name="us-east-1")

    try:
        response = client.get_products(
            ServiceCode="AmazonEC2",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
                {"Type": "TERM_MATCH", "Field": "location", "Value": location},
                {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
                {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
                {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
                {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
            ],
            MaxResults=10,
        )

        price_list = response.get("PriceList", [])

        if not price_list:
            print(
                f"No pricing found for instance={instance_type}, "
                f"region={region_code} ({location})"
            )
            return None

        item = json.loads(price_list[0])

        ondemand_terms = item.get("terms", {}).get("OnDemand", {})
        if not ondemand_terms:
            print("No OnDemand terms found")
            return None

        term = next(iter(ondemand_terms.values()))
        dimensions = next(iter(term["priceDimensions"].values()))

        price = dimensions["pricePerUnit"].get("USD")
        return float(price) if price else None

    except Exception as e:
        print(f"AWS pricing error ({instance_type}, {region_code}): {e}")
        return None


def get_azure_price(instance, region):
    try:
        print("Azure pricing lookup:", instance, region)

        url = "https://prices.azure.com/api/retail/prices"

        # ---------- BLOB STORAGE ----------
        if "blob" in instance.lower() or "storage" in instance:
            params = {
                "$filter": (
                    "serviceName eq 'Storage' "
                    "and contains(productName, 'Blob') "
                    "and contains(meterName, 'Data Stored') "
                    "and contains(skuName, 'Hot') "
                    f"and armRegionName eq '{region}' "
                    "and priceType eq 'Consumption'"
                )
            }

        # ---------- VM ----------
        elif instance.lower() == "vm" or instance.upper().startswith("DS"):
            params = {
                "$filter": (
                    "serviceName eq 'Virtual Machines' "
                    "and serviceFamily eq 'Compute' "
                    f"and contains(skuName, '{instance.upper()}')"
                    f"and armRegionName eq '{region}' "
                    "and priceType eq 'Consumption'"
                )
            }

        else:
            print("Unsupported Azure instance")
            return 0.0

        # 🔑 PAGINATION LOOP (THIS IS THE KEY)
        while True:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()

            items = data.get("Items", [])
            if items:
                return float(items[0]["retailPrice"])

            next_link = data.get("NextPageLink")
            if not next_link:
                break

            url = next_link
            params = None  # Azure requires params ONLY on first call

        print("No Azure pricing rows found")
        return 0.0

    except Exception as e:
        print("Azure pricing error:", e)
        return 0.0

def infer_gcp_machine_type(vcpus, memory_gb):
    for mtype, (cpu, ram) in MACHINE_SPECS.items():
        if cpu == vcpus and abs(ram - memory_gb) < 0.5:
            return mtype
    raise ValueError(
        f"No matching GCP machine type for vCPUs={vcpus}, RAM={memory_gb}GB"
    )

def normalize_region(region):
    return region.split("-")[0] + "-" + region.split("-")[1]

COMPUTE_SERVICE = "services/6F81-5844-456A"

# Map preset machine → vCPU & RAM
MACHINE_SPECS = {
    "n1-standard-1": (1, 3.75),
    "n1-standard-2": (2, 7.5),
    "n1-standard-4": (4, 15),
    "n1-standard-8": (8, 30),
}

def _get_gcp_custom_unit_prices():
    """
    Fetch hourly unit prices for:
    - 1 vCPU
    - 1 GB RAM
    (Custom machine SKUs)
    """
    client = billing_v1.CloudCatalogClient()
    cpu_price = None
    ram_price = None

    for sku in client.list_skus(parent=COMPUTE_SERVICE):

        desc = sku.description.lower()

        if "custom instance" not in desc:
            continue
        if "preemptible" in desc or "windows" in desc:
            continue
        if not sku.pricing_info:
            continue

        expr = sku.pricing_info[0].pricing_expression
        if not expr.tiered_rates:
            continue

        unit = expr.tiered_rates[0].unit_price
        price = unit.units + unit.nanos / 1e9

        if "second" in expr.usage_unit.lower():
            price *= 3600

        if "core" in desc and cpu_price is None:
            cpu_price = price

        elif "ram" in desc and ram_price is None:
            ram_price = price

        if cpu_price and ram_price:
            break

    if cpu_price is None or ram_price is None:
        raise RuntimeError("Failed to resolve GCP custom unit prices")

    return cpu_price, ram_price


def get_gcp_price(instance_type, region):
    """
    Public API — matches your required structure
    """
    print("[GCP] get_gcp_price:", instance_type, region)

    if instance_type not in MACHINE_SPECS:
        raise ValueError(f"Unsupported GCP instance type: {instance_type}")

    vcpus, ram_gb = MACHINE_SPECS[instance_type]

    # 🔑 Stable pricing source
    cpu_unit_price, ram_unit_price = _get_gcp_custom_unit_prices()

    hourly_cost = cpu_unit_price * vcpus + ram_unit_price * ram_gb
    print("[GCP] Hourly cost:", hourly_cost)

    return round(hourly_cost, 4)

