import requests, base64, json, re, os
from datetime import datetime
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponseBadRequest
from .models import Transaction
from .forms import PaymentForm
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Retrieve variables from the environment
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
MPESA_PASSKEY = os.getenv("MPESA_PASSKEY")
MPESA_SHORTCODE = os.getenv("MPESA_SHORTCODE")
CALLBACK_URL = os.getenv("CALLBACK_URL")
MPESA_BASE_URL = os.getenv("MPESA_BASE_URL")

# Phone number formatting and validation
def format_phone_number(phone):
    phone = phone.replace("+", "")
    if re.match(r"^254\d{9}$", phone):
        return phone
    elif phone.startswith("0") and len(phone) == 10:
        return "254" + phone[1:]
    else:
        raise ValueError("Invalid phone number format")

# Generate M-Pesa access token
def generate_access_token():
    """
    Generate M-Pesa access token using consumer key and secret.
    """
    CONSUMER_KEY = ""
    CONSUMER_SECRET = ""

    credentials = f"{CONSUMER_KEY}:{CONSUMER_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/json",
    }
    response = requests.get(
        f"{MPESA_BASE_URL}/oauth/v1/generate?grant_type=client_credentials",
        headers=headers,
    )
    response_data = response.json()

    if "access_token" in response_data:
        return response_data["access_token"]
    else:
        raise Exception(f"Error generating access token: {response_data}")




# Initiate STK Push and handle response
def initiate_stk_push(phone_number, amount):
    access_token = generate_access_token()

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # Generate dynamic password and timestamp
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password_string = f"{MPESA_SHORTCODE}{MPESA_PASSKEY}{timestamp}"
    password = base64.b64encode(password_string.encode()).decode()

    request_body = {
        "BusinessShortCode": MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone_number,
        "PartyB": MPESA_SHORTCODE,
        "PhoneNumber": phone_number,
        "CallBackURL": CALLBACK_URL,
        "AccountReference": "TestAccount",
        "TransactionDesc": "Payment for goods",
    }

    response = requests.post(
        f"{MPESA_BASE_URL}/mpesa/stkpush/v1/processrequest",
        json=request_body,
        headers=headers,
    )
    response_data = response.json()

    # Log the full response for debugging
    print(f"STK Push Response: {response.status_code}, {response.text}")

    if response_data.get("ResponseCode") == "0":
        return {
            "success": True,
            "message": response_data.get("CustomerMessage"),
            "checkout_request_id": response_data.get("CheckoutRequestID"),
        }
    else:
        return {
            "success": False,
            "message": response_data.get("errorMessage", "STK Push request failed."),
        }


# Payment View
def payment_view(request):
    if request.method == "POST":
        form = PaymentForm(request.POST)
        if form.is_valid():
            try:
                phone = format_phone_number(form.cleaned_data["phone_number"])
                amount = form.cleaned_data["amount"]
                response = initiate_stk_push(phone, amount)

                if response["success"]:
                    return render(request, "pending.html", {
                        "checkout_request_id": response["checkout_request_id"],
                        "success_message": response["message"]
                    })
                else:
                    return render(request, "payment_form.html", {
                        "form": form,
                        "error_message": response["message"]
                    })

            except ValueError as e:
                return render(request, "payment_form.html", {"form": form, "error_message": str(e)})
            except Exception as e:
                return render(request, "payment_form.html", {"form": form, "error_message": f"An unexpected error occurred: {str(e)}"})

    else:
        form = PaymentForm()

    return render(request, "payment_form.html", {"form": form})

# Query STK Push status
def query_stk_push(checkout_request_id):
    try:
        token = generate_access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        password = base64.b64encode(
            (MPESA_SHORTCODE + MPESA_PASSKEY + timestamp).encode()
        ).decode()

        request_body = {
            "BusinessShortCode": MPESA_SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id
        }

        response = requests.post(
            f"{MPESA_BASE_URL}/mpesa/stkpushquery/v1/query",
            json=request_body,
            headers=headers,
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to query STK status: {response.status_code}, {response.text}")

        return response.json()

    except requests.RequestException as e:
        return {"error": str(e)}

# View to query the STK status and return it to the frontend
def stk_status_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            checkout_request_id = data.get('checkout_request_id')

            status = query_stk_push(checkout_request_id)

            return JsonResponse({"status": status})
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

    return JsonResponse({"error": "Invalid request method"}, status=405)

@csrf_exempt  # To allow POST requests from external sources like M-Pesa
def payment_callback(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST requests are allowed")

    try:
        callback_data = json.loads(request.body)
        result_code = callback_data["Body"]["stkCallback"]["ResultCode"]

        if result_code == 0:
            checkout_id = callback_data["Body"]["stkCallback"]["CheckoutRequestID"]
            metadata = callback_data["Body"]["stkCallback"]["CallbackMetadata"]["Item"]

            amount = next(item["Value"] for item in metadata if item["Name"] == "Amount")
            mpesa_code = next(item["Value"] for item in metadata if item["Name"] == "MpesaReceiptNumber")
            phone = next(item["Value"] for item in metadata if item["Name"] == "PhoneNumber")

            Transaction.objects.create(
                amount=amount, 
                checkout_id=checkout_id, 
                mpesa_code=mpesa_code, 
                phone_number=phone, 
                status="Success"
            )
            return JsonResponse({"ResultCode": 0, "ResultDesc": "Payment successful"})

        return JsonResponse({"ResultCode": result_code, "ResultDesc": "Payment failed"})

    except (json.JSONDecodeError, KeyError) as e:
        return HttpResponseBadRequest(f"Invalid request data: {str(e)}")
