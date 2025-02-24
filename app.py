import os
import requests
import uuid
import fitz 
from flask import Flask, request, jsonify

app = Flask(__name__)


GELATO_API_KEY = os.getenv("GELATO_API_KEY")
GELATO_PRODUCT_ID = os.getenv("GELATO_PRODUCT_ID")
GELATO_API_URL = "https://order.gelatoapis.com/v4/orders"

HEADERS = {
    "X-API-KEY": GELATO_API_KEY,
    "Content-Type": "application/json",
}


TEMP_DIR = "./temp_pdfs"
PDF_DIR = "./processed_pdfs"
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(PDF_DIR, exist_ok=True)


def download_pdf(url):
    """Downloads PDF from a given URL."""
    try:
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            pdf_path = os.path.join(TEMP_DIR, "input.pdf")
            with open(pdf_path, "wb") as file:
                file.write(response.content)
            print(f"✅ PDF downloaded: {pdf_path}")
            return pdf_path
        else:
            print(f"❌ Failed to download PDF: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Error downloading PDF: {e}")
        return None


def ensure_correct_page_count(pdf_path, output_path):
    """
    Ensures the PDF meets Gelato's required 39-page format:
    - Page 1: Cover spread (landscape)
    - Page 2: Blank
    - Page 3-N: Content
    - Last page: Blank
    """
    try:
        doc = fitz.open(pdf_path)
        page_count = len(doc)

        print(f"🔹 Original PDF has {page_count} pages.")

       
        while page_count < 39:
            doc.insert_pdf(fitz.open())  
            page_count += 1

        print(f"✅ Adjusted PDF to {page_count} pages.")

        
        doc.save(output_path)
        doc.close()
        return output_path, page_count

    except Exception as e:
        print(f"❌ Error adjusting page count: {e}")
        return None, None


def upload_binary(file_path, s3_key, file_type="application/pdf"):
    """Simulate uploading file to S3 and return URL (replace with actual S3 logic)."""
    s3_url = f"https://mock-s3-bucket.com/{s3_key}"
    print(f"✅ File uploaded to S3: {s3_url}")
    return s3_url


def order_book_with_gelato(pdf_url, customer_data):
    """
    Places an order with Gelato.
    """
    payload = {
        "orderType": "order",
        "orderReferenceId": f"order-{uuid.uuid4().hex[:8]}",
        "customerReferenceId": f"customer-{uuid.uuid4().hex[:8]}",
        "currency": "USD",
        "items": [
            {
                "itemReferenceId": f"item-{uuid.uuid4().hex[:8]}",
                "productUid": GELATO_PRODUCT_ID,
                "files": [{"type": "default", "url": pdf_url}],
                "quantity": 1,
                "pageCount": 39  
            }
        ],
        "shipmentMethodUid": "standard",
        "shippingAddress": {
            "companyName": customer_data["customer_name"],
            "firstName": customer_data["customer_name"].split()[0],
            "lastName": customer_data["customer_name"].split()[-1],
            "addressLine1": customer_data["address"],
            "city": customer_data["city"],
            "state": "",
            "postCode": customer_data["postal_code"],
            "country": customer_data["country"],
            "email": customer_data["email"]
        }
    }

    try:
        response = requests.post(GELATO_API_URL, headers=HEADERS, json=payload, timeout=30)
        if response.status_code == 201:
            order_data = response.json()
            print(f"✅ Book order created! Order ID: {order_data['id']}")
            return order_data
        else:
            print(f"❌ Error placing order: {response.text}")
            return None
    except Exception as e:
        print(f"❌ API request failed: {e}")
        return None


@app.route("/order-book", methods=["POST"])
def order_book():
    data = request.json
    print(f"📥 Received Order Request: {data}")

    
    required_fields = ["user_id", "pdf_url", "customer_name", "address", "city", "country", "postal_code", "email"]
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    
    pdf_path = download_pdf(data["pdf_url"])
    if not pdf_path:
        return jsonify({"error": "Failed to download PDF"}), 500

    
    corrected_pdf_path, actual_page_count = ensure_correct_page_count(pdf_path, os.path.join(PDF_DIR, "gelato_ready.pdf"))
    if not corrected_pdf_path or actual_page_count != 39:
        return jsonify({"error": "Failed to generate a correctly formatted PDF"}), 500

    
    try:
        s3_pdf_key = f"{data['user_id']}/pdf/gelato_ready.pdf"
        gelato_pdf_url = upload_binary(corrected_pdf_path, s3_pdf_key)
    except Exception as e:
        print(f"❌ Failed to upload PDF to S3: {e}")
        return jsonify({"error": "Failed to upload PDF"}), 500

    
    order = order_book_with_gelato(gelato_pdf_url, data)
    if not order:
        return jsonify({"error": "Failed to place book order"}), 500

    return jsonify({
        "message": "Book order created successfully!",
        "order_id": order["id"],
        "gelato_pdf_url": gelato_pdf_url
    })


if __name__ == "__main__":
    app.run(debug=True)
