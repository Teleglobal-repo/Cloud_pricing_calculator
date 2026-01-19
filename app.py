import os
import uuid
import threading
from datetime import datetime
import os
import pandas as pd
from flask import Flask, request, jsonify, send_file

from llm_with_tools import generate_boq, OUTPUT_CSV
from flask import  render_template
# =================================================
# FLASK APP
# =================================================
app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SAMPLE_TEMPLATES_FOLDER = "sample_templates"
SAMPLE_TEMPLATES = {
    "AWS": os.path.join(os.getcwd(), SAMPLE_TEMPLATES_FOLDER, "aws_inventory_sample.csv"),
    "AZURE": os.path.join(os.getcwd(), SAMPLE_TEMPLATES_FOLDER, "azure_inventory_sample.csv"),
    "GCP": os.path.join(os.getcwd(), SAMPLE_TEMPLATES_FOLDER, "gcp_inventory_sample.csv"),
}

# =================================================
# IN-MEMORY JOB STORE
# (use Redis/DB later for scale)
# =================================================
JOB_STORE = {}
"""
JOB_STORE[job_id] = {
    status: pending | running | completed | failed
    message: str
    output_file: str | None
}
"""
# =================================================
# RETURN UI
# =================================================
@app.route("/")
def home():
    return render_template("index.html")
@app.route("/boq")
def boq():
    return render_template("boq.html")

# =================================================
# HEALTH CHECK
# =================================================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# =================================================
# SAMPLE TEMPLATE DOWNLOAD
# =================================================
@app.route("/api/sample-template/<provider>", methods=["GET"])
def download_sample_template(provider):
    provider = provider.upper()
    file_path = SAMPLE_TEMPLATES.get(provider)

    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "Sample template not found"}), 404

    return send_file(
        file_path,
        as_attachment=True,
        download_name=f"{provider.lower()}_inventory_sample.csv"
    )


# =================================================
# UPLOAD INVENTORY
# =================================================
@app.route("/api/upload", methods=["POST"])
def upload_inventory():
    if "file" not in request.files:
        return jsonify({"error": "File is required"}), 400

    file = request.files["file"]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{file.filename}"
    file_path = os.path.join(UPLOAD_FOLDER, filename)

    file.save(file_path)

    return jsonify({
        "message": "File uploaded successfully",
        "file_path": file_path
    })


# =================================================
# PREVIEW INVENTORY
# =================================================
@app.route("/api/preview", methods=["POST"])
def preview_inventory():
    data = request.get_json()
    file_path = data.get("file_path")

    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".csv":
        df = pd.read_csv(file_path, encoding="latin1")
    elif ext in [".xls", ".xlsx"]:
        df = pd.read_excel(file_path)
    else:
        return jsonify({"error": "Unsupported file format"}), 400

    return jsonify({
        "columns": list(df.columns),
        "rows": df.head(20).to_dict("records")
    })


# =================================================
# BACKGROUND BOQ TASK
# =================================================
def boq_background_task(job_id, file_path, provider):
    try:
        JOB_STORE[job_id]["status"] = "running"
        JOB_STORE[job_id]["message"] = "Generating BOQ"

        generate_boq(file_path, provider)

        if not os.path.exists(OUTPUT_CSV):
            raise RuntimeError("BOQ output not generated")

        JOB_STORE[job_id]["status"] = "completed"
        JOB_STORE[job_id]["message"] = "BOQ generated successfully"
        JOB_STORE[job_id]["output_file"] = OUTPUT_CSV

    except Exception as e:
        JOB_STORE[job_id]["status"] = "failed"
        JOB_STORE[job_id]["message"] = str(e)


# =================================================
# GENERATE BOQ (ASYNC)
# =================================================
@app.route("/api/generate-boq", methods=["POST"])
def generate_boq_api():
    data = request.get_json()
    
    file_path = data.get("file_path")
    provider = data.get("provider")

    if not file_path or not provider:
        return jsonify({"error": "file_path and provider required"}), 400

    if not os.path.exists(file_path):
        return jsonify({"error": "Uploaded file not found"}), 404

    job_id = str(uuid.uuid4())

    JOB_STORE[job_id] = {
        "status": "pending",
        "message": "Job created",
        "output_file": None
    }

    thread = threading.Thread(
        target=boq_background_task,
        args=(job_id, file_path, provider),
        daemon=True
    )
    thread.start()

    return jsonify({
        "job_id": job_id,
        "status": "pending"
    })


# =================================================
# JOB STATUS (POLLING)
# =================================================
@app.route("/api/job-status/<job_id>", methods=["GET"])
def job_status(job_id):
    job = JOB_STORE.get(job_id)

    if not job:
        return jsonify({"error": "Invalid job ID"}), 404

    return jsonify({
        "job_id": job_id,
        "status": job["status"],
        "message": job["message"],
        "download_url": (
            "/api/download-boq" if job["status"] == "completed" else None
        )
    })


# =================================================
# DOWNLOAD BOQ
# =================================================
@app.route("/api/download-boq", methods=["GET"])
def download_boq():
    if not os.path.exists(OUTPUT_CSV):
        return jsonify({"error": "BOQ not found"}), 404

    return send_file(
        OUTPUT_CSV,
        as_attachment=True,
        download_name="boq_output_tools.csv"
    )


# =================================================
# ENTRY POINT
# =================================================
# =================================================
server = app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=True)