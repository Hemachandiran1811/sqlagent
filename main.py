from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import StreamingResponse
import os
import requests

app = FastAPI()

endpoint = "https://ai-hemachandirant2000ai2828457738479555.cognitiveservices.azure.com"
path = "/translator/document:translate"
url = endpoint + path

headers = {
    "Ocp-Apim-Subscription-Key": "EljYKuTJXi7Sshri8p84RmhDXI73Sr85WatFlNVb9gmppeYg7o0IJQQJ99BAACYeBjFXJ3w3AAAAACOG9Zf5"
}

@app.post("/translate/")
async def translate_document(
    target_language: str = Form(...),
    file: UploadFile = File(...)
):
    try:
        # Save the uploaded file temporarily
        input_file_path = f"./uploads/{file.filename}"
        output_file_path = f"./uploads/translated_{file.filename}"
        with open(input_file_path, "wb") as temp_file:
            temp_file.write(await file.read())

        # Prepare parameters (exclude sourceLanguage for auto-detection)
        params = {
            "targetLanguage": target_language,
            "api-version": "2023-11-01-preview"
        }

        # Prepare files for the request
        with open(input_file_path, "rb") as document:
            files = {
                "document": (os.path.basename(input_file_path), document, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            }

            # Make the request to the Azure Translation API
            response = requests.post(url, headers=headers, params=params, files=files)

        if response.status_code == 200:
            # Save the translated document
            with open(output_file_path, "wb") as output_file:
                output_file.write(response.content)

            # Stream the saved document as a response
            def iterfile():
                with open(output_file_path, "rb") as f:
                    yield from f

            return StreamingResponse(
                iterfile(),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f"attachment; filename=translated_{file.filename}"}
            )
        else:
            return {"error": response.json()}

    except Exception as e:
        return {"error": str(e)}
