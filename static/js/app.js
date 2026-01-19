let uploadedFilePath = null;
let jobId = null;

function getProvider() {
    const selected = document.querySelector('input[name="provider"]:checked');
    if (!selected) {
        alert("Please select a cloud provider (AWS / Azure / GCP)");
        return null;
    }
    const provider = selected.value;
    sessionStorage.setItem("selectedProvider", provider);
    return provider;
}

async function uploadFile() {
    const fileInput = document.getElementById("fileInput");
    const file = fileInput.files[0];
    if (!file) {
        alert("Please select a file before uploading");
        return;
    }
    document.getElementById("boq-loader-overlay").style.display = "flex";
    const progressFill = document.getElementById("boq-progress-fill");
    const progressText = document.getElementById("boq-progress-text");
    let progress = 0;
    const fakeProgress = setInterval(() => {
        if (progress < 90) {
            progress += 5;
            progressFill.style.width = progress + "%";
            progressText.innerText = progress + "%";
        }
    }, 200);
    const formData = new FormData();
    formData.append("file", file);
    try {
        const res = await fetch("/api/upload", {
            method: "POST",
            body: formData
        });
        const data = await res.json();
        if (!data.file_path) {
            throw new Error(data.error || "Upload failed");
        }
        uploadedFilePath = data.file_path;
        sessionStorage.setItem("uploadedFilePath", uploadedFilePath);
        clearInterval(fakeProgress);
        progressFill.style.width = "100%";
        progressText.innerText = "100%";
        setTimeout(() => {
            window.location.href = "/boq";
        }, 800);
    } catch (err) {
        clearInterval(fakeProgress);
        alert(err.message);
        document.getElementById("boq-loader-overlay").style.display = "none";
    }
}
function downloadSample() {
    const selected = document.querySelector('input[name="provider"]:checked');

    if (!selected) {
        alert("Please select a cloud provider first");
        return;
    }

    const provider = selected.value;

    // ✅ CORRECT BACKEND ENDPOINT
    const downloadUrl = `/api/sample-template/${provider}`;

    // Force file download
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `${provider.toLowerCase()}_inventory_sample.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

async function previewData() {
    const res = await fetch("/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: uploadedFilePath })
    });
    const data = await res.json();
    renderTable(data.columns, data.rows);
}

function renderTable(columns, rows) {
    const table = document.getElementById("previewTable");
    table.innerHTML = "";
    const head = "<tr>" + columns.map(c => `<th>${c}</th>`).join("") + "</tr>";
    const body = rows.map(r =>
        "<tr>" + columns.map(c => `<td>${r[c]}</td>`).join("") + "</tr>"
    ).join("");
    table.innerHTML = `<thead>${head}</thead><tbody>${body}</tbody>`;
}

async function generateBOQ() {
    if (!uploadedFilePath) {
        alert("Please upload inventory file first");
        return;
    }
    const provider = getProvider();
    if (!provider) return;
    showGenerateLoader();
    const res = await fetch("/api/generate-boq", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            file_path: uploadedFilePath,
            provider: provider
        })
    });
    const data = await res.json();
    if (!data.job_id) {
        hideGenerateLoader();
        document.getElementById("status").innerText =
            data.error || "Failed to start BOQ generation";
        return;
    }
    jobId = data.job_id;
    pollJob();
}

function pollJob() {
    const interval = setInterval(async () => {
        const res = await fetch(`/api/job-status/${jobId}`);
        const data = await res.json();
        if (data.status === "completed") {
            clearInterval(interval);

            const percent = document.querySelector(".btn-percentage");
            if (percent) percent.innerText = "100%";

            setTimeout(() => {
                hideGenerateLoader();
            }, 500);
            const provider =
                document.querySelector('input[name="provider"]:checked')?.value ||
                sessionStorage.getItem("selectedProvider") ||
                "";
            const titleEl = document.getElementById("boqGeneratedTitle");
            if (titleEl) {
                titleEl.innerText = `BOQ Generated Successfully for ${provider}`;
                titleEl.style.display = "block";
            }
            await loadBOQTable(data.download_url);
            let downloadBtn = document.getElementById("downloadLink");
            if (!downloadBtn) {
                downloadBtn = document.createElement("a");
                downloadBtn.id = "downloadLink";
                downloadBtn.className = "boq-download";
                downloadBtn.innerHTML = `
            <span class="boq-download-icon">
             <img
               src="https://n-teleglobalwebsitemedia.s3.ap-south-1.amazonaws.com/New-React-website-images/Vector.png"
               class="download-icon"
             />
            </span>
            <span class="boq-download-text">Download BOQ Report</span>
            `;
                downloadBtn.href = "javascript:void(0)";
                downloadBtn.onclick = () => openBOQFormPopup(data.download_url);
                downloadBtn.style.display = "inline-block";
                document.getElementById("boqTable").after(downloadBtn);
            }
        }
    }, 2000);
}

async function loadBOQTable(downloadUrl) {
    const res = await fetch(downloadUrl);
    const csvText = await res.text();
    const rows = csvText.trim().split("\n");
    const headers = rows[0].split(",");
    const data = rows.slice(1).map(row => {
        const values = row.split(",");
        const obj = {};
        headers.forEach((h, i) => {
            obj[h.trim()] = values[i]?.trim();
        });
        return obj;
    });
    renderBOQTable(headers, data);
}

function renderBOQTable(columns, rows) {
    const table = document.getElementById("boqTable");
    if (!table) return;
    const head =
        "<tr>" + columns.map(c => `<th>${c}</th>`).join("") + "</tr>";
    const body = rows
        .map(r =>
            "<tr>" +
            columns.map(c => `<td>${r[c]}</td>`).join("") +
            "</tr>"
        )
        .join("");
    table.innerHTML = `<thead>${head}</thead><tbody>${body}</tbody>`;
}

document.addEventListener("DOMContentLoaded", () => {
    const previewTable = document.getElementById("previewTable");
    if (!previewTable) return;
    const storedPath = sessionStorage.getItem("uploadedFilePath");
    if (!storedPath) return;
    uploadedFilePath = storedPath;
    previewData();
    const generateBtn = document.querySelector(".generate");
    if (generateBtn) {
        generateBtn.disabled = false;
    }
});

function isCorporateEmail(email) {
    const publicDomains = [
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "rediffmail.com",
        "icloud.com",
        "aol.com",
        "protonmail.com"
    ];
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailPattern.test(email)) return false;
    const domain = email.split("@")[1].toLowerCase();
    return !publicDomains.includes(domain);
}

let boqDownloadUrl = "";
function openBOQFormPopup(downloadUrl) {
    boqDownloadUrl = downloadUrl;
    document.getElementById("boq-form-overlay").style.display = "flex";
}

function validateSimpleFormHTML() {
    let valid = true;
    const name = document.getElementById("sf-name");
    const email = document.getElementById("sf-email");
    const phone = document.getElementById("sf-phone");
    const company = document.getElementById("sf-company");
    const callingCode = document.getElementById("sf-callingCode");
    const message = document.getElementById("sf-message");
    [name, email, phone, company, callingCode].forEach(i =>
        i.classList.remove("input-error")
    );
    message.innerHTML = "";
    if (!name.value.trim()) {
        name.classList.add("input-error");
        valid = false;
    }
    if (!email.value.trim() || !isCorporateEmail(email.value)) {
        email.classList.add("input-error");
        message.innerHTML =
            `<div class="sf-message error">
                Please fill required field with your official work email.
            </div>`;
        valid = false;
    }
    if (!phone.value.trim()) {
        phone.classList.add("input-error");
        valid = false;
    }
    if (!callingCode.value) {
        callingCode.classList.add("input-error");
        valid = false;
    }
    return valid;
}


function closeBOQFormPopup() {
    const popup = document.getElementById("boq-form-overlay");
    if (popup) {
        popup.style.display = "none";
    }
    document.getElementById("sf-name").value = "";
    document.getElementById("sf-email").value = "";
    document.getElementById("sf-phone").value = "";
    document.getElementById("sf-company").value = "";
    document.getElementById("sf-callingCode").value = "";
    document.getElementById("sf-message").innerHTML = "";
}

async function handleSimpleSubmitHTML() {
    if (!validateSimpleFormHTML()) return;
    const btn = document.getElementById("sf-submit-btn");
    const btnText = btn.querySelector(".sf-btn-text");
    const progressBar = btn.querySelector(".sf-btn-progress");
    btn.disabled = true;
    btnText.innerText = "Downloading file...";
    progressBar.style.width = "0%";
    let progress = 0;
    const progressInterval = setInterval(() => {
        if (progress < 90) {
            progress += 10;
            progressBar.style.width = progress + "%";
        }
    }, 300);

    const payload = {
        FirstName: document.getElementById("sf-name").value,
        Company: document.getElementById("sf-company").value.trim() || "NA",
        Email: document.getElementById("sf-email").value,
        CallingCode: document.getElementById("sf-callingCode").value,
        Phone: document.getElementById("sf-phone").value,
        RequestUrl: window.location.href
    };

    try {
        await fetch("https://teleglobals.com/submit-form/simple-contact", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        clearInterval(progressInterval);
        progressBar.style.width = "100%";

        document.getElementById("sf-message").innerHTML =
            `<div class="sf-message success">
                Submitted successfully. Downloading BOQ...
            </div>`;

        setTimeout(() => {
            closeBOQFormPopup();
        }, 600);

        setTimeout(() => {
            const a = document.createElement("a");
            a.href = boqDownloadUrl;
            a.download = "";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }, 900);

    } catch (e) {
        clearInterval(progressInterval);
        progressBar.style.width = "0%";
        btnText.innerText = "Download";

        document.getElementById("sf-message").innerHTML =
            `<div class="sf-message error">
                Something went wrong. Please try again.
            </div>`;
    } finally {
        setTimeout(() => {
            btn.disabled = false;
            btnText.innerText = "Download";
            progressBar.style.width = "0%";
        }, 1200);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const savedProvider = sessionStorage.getItem("selectedProvider");
    if (!savedProvider) return;
    const radio = document.querySelector(
        `input[name="provider"][value="${savedProvider}"]`
    );
    if (radio) {
        radio.checked = true;
    }
});

let boqProgress = 0;
let boqProgressInterval = null;

function showGenerateLoader() {
    const btn = document.querySelector(".boq-generate-btn");
    if (!btn) return;
    const text = btn.querySelector(".btn-text");
    const percent = btn.querySelector(".btn-percentage");
    btn.disabled = true;
    text.innerText = "Generating...";
    percent.style.display = "inline-block";
    percent.innerText = "0%";
    boqProgress = 0;
    boqProgressInterval = setInterval(() => {
        if (boqProgress < 90) {
            boqProgress += 3;
            percent.innerText = `${boqProgress}%`;
        }
    }, 500);
}


function hideGenerateLoader() {
    const btn = document.querySelector(".boq-generate-btn");
    if (!btn) return;

    const text = btn.querySelector(".btn-text");
    const percent = btn.querySelector(".btn-percentage");

    clearInterval(boqProgressInterval);

    percent.innerText = "100%";

    setTimeout(() => {
        percent.style.display = "none";
        text.innerText = "Verify Document & Generate Report";
        btn.disabled = false;
    }, 600);
}

