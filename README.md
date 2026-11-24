# FactoryFlow — Food Manufacturing Management System

A runnable Flask + SQLite internship project starter for a small packaged-food manufacturer. It includes five role-based demo logins, sales orders, Factory Admin approval, GST invoice PDF, dispatch, production consumption, inventory ledger, collections, CSV sales export, audit trail and an AI-style demand forecast using scikit-learn Linear Regression.

## 1. Requirements
- Windows 10/11
- Python 3.10 or later
- VS Code
- Internet connection for Bootstrap, icons, Google Fonts and Chart.js CDN assets (the backend works locally without these assets, but the dashboard styling/chart needs internet).

## 2. Open and run in VS Code
1. Extract `FactoryFlow_VSCode.zip`.
2. Open the extracted `FactoryFlow_VSCode` folder in VS Code.
3. Open **Terminal → New Terminal**.
4. Create a virtual environment:

   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   ```

   If PowerShell blocks activation, run:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .venv\Scripts\Activate.ps1
   ```

5. Install packages:

   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

6. Start the app:

   ```powershell
   python run.py
   ```

7. Open `http://127.0.0.1:5000` in your browser.

The SQLite database `factoryflow.db` is created automatically on first run and demo data is seeded.

## 3. Demo login accounts

| Role | Username | Password |
|---|---|---|
| Owner | `owner` | `Owner@123` |
| Factory Admin | `admin` | `Admin@123` |
| Salesman | `salesman_a` | `Sales@123` |
| Production Supervisor | `production` | `Prod@123` |
| Accountant/Auditor | `accountant` | `Audit@123` |

These are demonstration credentials. Change them and set a strong `SECRET_KEY` before deploying anywhere public.

## 4. Benchmark workflow to demonstrate

Use the following sequence to reproduce the problem statement's scenario:

1. Sign in as **Production Supervisor** (`production` / `Prod@123`).
2. Open **Purchases** and receive `60 kg` Flour at `₹45` per kg.
3. Open **Production** and keep the default benchmark values:
   - Planned output 200 packets; actual good output 188
   - Flour 40 kg; oil 10.5 L; spice mix 1.2 kg
   - Damaged pouches 6; cartons used 9
   - Labour ₹1,200; power & gas ₹600
4. Save the production run.
5. Check **Inventory & ledger**. Expected balances at this point:
   - Flour 120 kg
   - Oil 19.5 L
   - Spice mix 3.8 kg
   - Pouches 306 pieces
   - Cartons 21 pieces
   - Finished Murukku 238 packets
6. Sign in as **Salesman** (`salesman_a` / `Sales@123`), create an order for Retailer A for 150 packets.
7. Sign in as **Factory Admin** (`admin` / `Admin@123`), approve the order. It generates an intra-state GST invoice:
   - Taxable value ₹7,500
   - CGST ₹187.50
   - SGST ₹187.50
   - Total ₹7,875
8. From **GST invoices**, download the PDF and record dispatch. Finished stock becomes 88 packets.
9. From **Collections**, record ₹4,000 from Retailer A. Expected outstanding for that invoice is ₹3,875.
10. As Salesman, create an order for Distributor B for 120 packets. Factory Admin approval will flag a shortage of 32 packets because only 88 remain.
11. Open **AI predictions**. The app trains a simple Linear Regression model on 42 seeded daily demo sales observations and compares next-day predicted demand with the recent 7-day average.

## 5. AI prediction explanation
- `sales_history` is a separate demo historical dataset; it does not affect the benchmark stock balances.
- The model uses elapsed day number as its input and daily packet sales as its target.
- The next-day forecast is compared with the average of the last seven historical days.
- Difference = forecast − recent 7-day average.
- Percentage difference = difference / recent 7-day average × 100.
- The page reports the history count and labels the dataset as demo history. Replace it with actual daily sales data for meaningful predictions. This is a simple baseline model, not a production-grade forecasting service.

## 6. Important implementation notes and limitations
- Money is stored as integer paise to avoid floating-point currency errors.
- Stock is calculated from the stock movement ledger, not typed into a balance field.
- The app includes seeded product, customers, raw materials and a Murukku BOM.
- The demo invoice PDF is a simplified invoice layout. It is not a certified GST/e-invoice integration; validate statutory fields and tax treatment with an accountant before real business use.
- This starter does not connect to a live GST portal, payment gateway, Tally, or e-invoice API.
- Role checks are included for the main write workflows. This is an educational project starter and should receive security review before production deployment.
- For a clean reset of demo data, stop the server and delete `factoryflow.db`; it will be recreated the next time `python run.py` runs.

## 7. Main project structure

```text
FactoryFlow_VSCode/
├── app.py
├── run.py
├── requirements.txt
├── README.md
├── factoryflow.db       # created on first run
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── orders.html
│   ├── invoices.html
│   ├── production.html
│   ├── inventory.html
│   ├── purchase.html
│   ├── payments.html
│   ├── ai.html
│   ├── reports.html
│   ├── customers.html
│   ├── audit.html
│   └── error.html
└── static/
    ├── style.css
    └── history.json
```
