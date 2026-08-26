import os
from google.cloud import documentai


PROJECT_ID = "397274844501"
LOCATION = "us"
PROCESSOR_ID = "a2b4394f5e0de5fe"

PDF_PATH = "./input_doc_location/handwritten_freight_bill_sample.pdf"


def process_document():
    client = documentai.DocumentProcessorServiceClient()

    processor_name = client.processor_path(
        PROJECT_ID,
        LOCATION,
        PROCESSOR_ID,
    )

    with open(PDF_PATH, "rb") as pdf_file:
        pdf_content = pdf_file.read()

    raw_document = documentai.RawDocument(
        content=pdf_content,
        mime_type="application/pdf",
    )

    request = documentai.ProcessRequest(
        name=processor_name,
        raw_document=raw_document,
    )

    result = client.process_document(request=request)
    document = result.document

    print("\n========== OCR RESULT ==========\n")
    print(document.text)

    print("\n========== END ==========\n")


if __name__ == "__main__":
    process_document()