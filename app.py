import os, sqlite3, io, csv
from datetime import date, datetime, timedelta
from functools import wraps
from decimal import Decimal, ROUND_HALF_UP
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, Response
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "factoryflow.db")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-demo-secret-key")

ROLES = ["Owner", "Factory Admin", "Salesman", "Production Supervisor", "Accountant/Auditor"]
DEMO_USERS = [
    ("owner", "Owner@123", "Owner"),
    ("admin", "Admin@123", "Factory Admin"),
    ("salesman_a", "Sales@123", "Salesman"),
    ("production", "Prod@123", "Production Supervisor"),
    ("accountant", "Audit@123", "Accountant/Auditor"),
]

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def money(paise):
    return "₹{:,.2f}".format((paise or 0) / 100)

def to_paise(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

@app.template_filter("inr")
def inr(value):
    return money(value)

def audit(con, action, detail):
    con.execute("INSERT INTO audit_logs(username, action, detail, created_at) VALUES(?,?,?,?)",
                (session.get("username", "system"), action, detail, datetime.now().isoformat(timespec="seconds")))

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def roles_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                flash("You do not have permission to access that page.", "warning")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return wrapper
    return deco

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, role TEXT);
    CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, name TEXT, state TEXT, gstin TEXT, phone TEXT);
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT, packet_size TEXT, selling_price_paise INTEGER, gst_rate REAL);
    CREATE TABLE IF NOT EXISTS materials(id INTEGER PRIMARY KEY, name TEXT, unit TEXT, qty REAL, rate_paise INTEGER);
    CREATE TABLE IF NOT EXISTS stock_movements(id INTEGER PRIMARY KEY, item_type TEXT, item_id INTEGER, item_name TEXT, movement TEXT, qty REAL, reference TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS bom_items(id INTEGER PRIMARY KEY, product_id INTEGER, material_id INTEGER, qty REAL);
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, customer_id INTEGER, salesman_id INTEGER, quantity INTEGER, status TEXT, created_at TEXT, notes TEXT);
    CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY, order_id INTEGER, invoice_no TEXT, taxable_paise INTEGER, cgst_paise INTEGER, sgst_paise INTEGER, igst_paise INTEGER, total_paise INTEGER, created_at TEXT);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, customer_id INTEGER, invoice_id INTEGER, amount_paise INTEGER, paid_on TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS production_runs(id INTEGER PRIMARY KEY, product_id INTEGER, planned_qty INTEGER, actual_qty INTEGER, damaged_pouches INTEGER, cartons_used INTEGER, labour_paise INTEGER, utilities_paise INTEGER, yield_pct REAL, created_at TEXT);
    CREATE TABLE IF NOT EXISTS sales_history(id INTEGER PRIMARY KEY, day TEXT, qty INTEGER);
    CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY, username TEXT, action TEXT, detail TEXT, created_at TEXT);
    """)
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        for username, password, role in DEMO_USERS:
            con.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                        (username, generate_password_hash(password), role))
    if con.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
        con.execute("INSERT INTO customers(name,state,gstin,phone) VALUES('Retailer A','Tamil Nadu','33ABCDE1234F1Z5','9876500001')")
        con.execute("INSERT INTO customers(name,state,gstin,phone) VALUES('Distributor B','Karnataka','29ABCDE1234F1Z5','9876500002')")
    if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        con.execute("INSERT INTO products(name,packet_size,selling_price_paise,gst_rate) VALUES('Murukku','200 g',5000,5)")
    if con.execute("SELECT COUNT(*) FROM materials").fetchone()[0] == 0:
        rows = [
            ("Flour","kg",100,4200), ("Oil","L",30,14000), ("Spice mix","kg",5,20000),
            ("200g pouch","pcs",500,250), ("Carton","pcs",30,1500)
        ]
        con.executemany("INSERT INTO materials(name,unit,qty,rate_paise) VALUES(?,?,?,?)", rows)
        # Opening finished goods
        con.execute("INSERT INTO stock_movements(item_type,item_id,item_name,movement,qty,reference,created_at) VALUES('product',1,'Murukku','OPENING',50,'Opening stock',?)",(datetime.now().isoformat(),))
        for row in rows:
            con.execute("INSERT INTO stock_movements(item_type,item_id,item_name,movement,qty,reference,created_at) VALUES('material',NULL,?,'OPENING',?,?,?)",
                        (row[0],row[2],"Opening stock",datetime.now().isoformat()))
    if con.execute("SELECT COUNT(*) FROM bom_items").fetchone()[0] == 0:
        # one batch = 200 packets; 40 kg flour, 10 L oil, 1.2 kg spice, 200 pouches, 10 cartons
        for material_id, qty in [(1,40),(2,10),(3,1.2),(4,200),(5,10)]:
            con.execute("INSERT INTO bom_items(product_id,material_id,qty) VALUES(1,?,?)",(material_id,qty))
    if con.execute("SELECT COUNT(*) FROM sales_history").fetchone()[0] == 0:
        # Clearly labelled demo history, separate from current stock ledger.
        base = date.today() - timedelta(days=42)
        vals = []
        for i in range(42):
            # deterministic weekly pattern with a gentle upward trend
            qty = 18 + (i // 7) * 2 + [0, 3, -2, 4, 1, 6, -1][i % 7]
            vals.append(((base + timedelta(days=i)).isoformat(), qty))
        con.executemany("INSERT INTO sales_history(day,qty) VALUES(?,?)", vals)
    con.commit()
    con.close()

def stock_product(con, product_id=1):
    row = con.execute("SELECT COALESCE(SUM(CASE WHEN movement IN ('OPENING','PRODUCTION_IN','RETURN') THEN qty WHEN movement='DISPATCH' THEN -qty ELSE 0 END),0) q FROM stock_movements WHERE item_type='product' AND item_id=?",(product_id,)).fetchone()
    return int(row["q"])

def stock_material(con, name):
    row = con.execute("SELECT COALESCE(SUM(CASE WHEN movement IN ('OPENING','PURCHASE_IN','RETURN') THEN qty WHEN movement IN ('PRODUCTION_ISSUE','DAMAGE') THEN -qty ELSE 0 END),0) q FROM stock_movements WHERE item_type='material' AND item_name=?",(name,)).fetchone()
    return float(row["q"])

def add_move(con, item_type, item_id, item_name, movement, qty, reference):
    con.execute("INSERT INTO stock_movements(item_type,item_id,item_name,movement,qty,reference,created_at) VALUES(?,?,?,?,?,?,?)",
                (item_type,item_id,item_name,movement,qty,reference,datetime.now().isoformat(timespec="seconds")))

@app.route("/")
def home():
    return redirect(url_for("dashboard") if session.get("user_id") else url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        con = db()
        user = con.execute("SELECT * FROM users WHERE username=?",(request.form.get("username","").strip(),)).fetchone()
        con.close()
        if user and check_password_hash(user["password_hash"], request.form.get("password","")):
            session.update(user_id=user["id"], username=user["username"], role=user["role"])
            flash("Welcome back. You are signed in as " + user["role"] + ".", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    con = db()
    stock = stock_product(con)
    flour, oil = stock_material(con,"Flour"), stock_material(con,"Oil")
    open_orders = con.execute("SELECT COUNT(*) n FROM orders WHERE status IN ('Pending','Approved')").fetchone()["n"]
    inv = con.execute("SELECT COALESCE(SUM(total_paise),0) total FROM invoices").fetchone()["total"]
    outstanding = con.execute("SELECT COALESCE(SUM(i.total_paise),0)-COALESCE((SELECT SUM(amount_paise) FROM payments),0) v FROM invoices i").fetchone()["v"]
    recent = con.execute("""SELECT o.id,o.quantity,o.status,o.created_at,c.name customer,u.username salesman
                            FROM orders o JOIN customers c ON c.id=o.customer_id JOIN users u ON u.id=o.salesman_id
                            ORDER BY o.id DESC LIMIT 6""").fetchall()
    con.close()
    return render_template("dashboard.html", stock=stock, flour=flour, oil=oil, open_orders=open_orders,
                           invoiced=inv, outstanding=outstanding, recent=recent)

@app.route("/orders", methods=["GET","POST"])
@login_required
def orders():
    con = db()
    if request.method == "POST":
        if session["role"] not in ("Salesman","Factory Admin"):
            flash("Only Salesman or Factory Admin can create orders.","warning")
            return redirect(url_for("orders"))
        customer_id = int(request.form["customer_id"])
        qty = max(1,int(request.form["quantity"]))
        notes = request.form.get("notes","")
        con.execute("INSERT INTO orders(customer_id,salesman_id,quantity,status,created_at,notes) VALUES(?,?,?,'Pending',?,?)",
                    (customer_id,session["user_id"],qty,datetime.now().isoformat(timespec="seconds"),notes))
        audit(con,"ORDER_CREATED",f"New order for customer #{customer_id}, quantity {qty}")
        con.commit()
        flash("Order submitted for Factory Admin verification.","success")
        return redirect(url_for("orders"))
    if session["role"] == "Salesman":
        rows = con.execute("""SELECT o.*,c.name customer,u.username salesman FROM orders o JOIN customers c ON c.id=o.customer_id JOIN users u ON u.id=o.salesman_id WHERE o.salesman_id=? ORDER BY o.id DESC""",(session["user_id"],)).fetchall()
    else:
        rows = con.execute("""SELECT o.*,c.name customer,u.username salesman FROM orders o JOIN customers c ON c.id=o.customer_id JOIN users u ON u.id=o.salesman_id ORDER BY o.id DESC""").fetchall()
    customers = con.execute("SELECT * FROM customers ORDER BY name").fetchall()
    con.close()
    return render_template("orders.html", rows=rows, customers=customers)

@app.route("/orders/<int:order_id>/approve", methods=["POST"])
@roles_required("Factory Admin")
def approve_order(order_id):
    con = db()
    order = con.execute("SELECT o.*,c.state FROM orders o JOIN customers c ON c.id=o.customer_id WHERE o.id=?",(order_id,)).fetchone()
    if not order:
        con.close(); flash("Order not found.","danger"); return redirect(url_for("orders"))
    if order["status"] != "Pending":
        con.close(); flash("Only pending orders can be approved.","warning"); return redirect(url_for("orders"))
    available = stock_product(con)
    if order["quantity"] > available:
        con.execute("UPDATE orders SET status='Shortage' WHERE id=?",(order_id,))
        audit(con,"ORDER_SHORTAGE",f"Order #{order_id}: requested {order['quantity']}, available {available}")
        con.commit(); con.close()
        flash(f"Insufficient finished stock. Available {available}; shortage {order['quantity']-available} packets.","warning")
        return redirect(url_for("orders"))
    product = con.execute("SELECT * FROM products WHERE id=1").fetchone()
    taxable = order["quantity"] * product["selling_price_paise"]
    gst = int(round(taxable * product["gst_rate"] / 100))
    if order["state"] == "Tamil Nadu":
        cgst, sgst, igst = gst//2, gst-gst//2, 0
    else:
        cgst, sgst, igst = 0, 0, gst
    total = taxable + cgst + sgst + igst
    invoice_no = f"FF-{date.today().strftime('%Y%m')}-{order_id:04d}"
    cur = con.execute("INSERT INTO invoices(order_id,invoice_no,taxable_paise,cgst_paise,sgst_paise,igst_paise,total_paise,created_at) VALUES(?,?,?,?,?,?,?,?)",
                      (order_id,invoice_no,taxable,cgst,sgst,igst,total,datetime.now().isoformat(timespec="seconds")))
    con.execute("UPDATE orders SET status='Approved' WHERE id=?",(order_id,))
    audit(con,"INVOICE_CREATED",f"{invoice_no} total {money(total)}")
    con.commit(); con.close()
    flash(f"Order approved and invoice {invoice_no} generated. Dispatch it after checking the invoice.","success")
    return redirect(url_for("invoices"))

@app.route("/orders/<int:order_id>/reject", methods=["POST"])
@roles_required("Factory Admin")
def reject_order(order_id):
    con=db(); con.execute("UPDATE orders SET status='Rejected' WHERE id=?",(order_id,))
    audit(con,"ORDER_REJECTED",f"Order #{order_id} rejected"); con.commit(); con.close()
    flash("Order rejected.","info"); return redirect(url_for("orders"))

@app.route("/invoices")
@login_required
def invoices():
    con=db()
    rows=con.execute("""SELECT i.*,o.quantity,c.name customer,c.state FROM invoices i JOIN orders o ON o.id=i.order_id JOIN customers c ON c.id=o.customer_id ORDER BY i.id DESC""").fetchall()
    con.close()
    return render_template("invoices.html", rows=rows)

@app.route("/invoices/<int:invoice_id>/dispatch", methods=["POST"])
@roles_required("Factory Admin")
def dispatch(invoice_id):
    con=db()
    inv=con.execute("SELECT i.*,o.quantity,o.id order_id FROM invoices i JOIN orders o ON o.id=i.order_id WHERE i.id=?",(invoice_id,)).fetchone()
    if not inv: con.close(); flash("Invoice not found.","danger"); return redirect(url_for("invoices"))
    order_state = con.execute("SELECT status FROM orders WHERE id=?",(inv["order_id"],)).fetchone()["status"]
    if order_state == "Dispatched":
        con.close(); flash("This invoice has already been dispatched.","warning"); return redirect(url_for("invoices"))
    if stock_product(con) < inv["quantity"]:
        con.close(); flash("Not enough finished goods to dispatch.","danger"); return redirect(url_for("invoices"))
    add_move(con,"product",1,"Murukku","DISPATCH",inv["quantity"],f"Invoice {inv['invoice_no']}")
    con.execute("UPDATE orders SET status='Dispatched' WHERE id=?",(inv["order_id"],))
    audit(con,"DISPATCH",f"{inv['invoice_no']} dispatched {inv['quantity']} packets")
    con.commit(); con.close(); flash("Dispatch recorded and finished stock reduced.","success")
    return redirect(url_for("invoices"))

@app.route("/payments", methods=["GET","POST"])
@login_required
def payments():
    con=db()
    if request.method=="POST":
        if session["role"] not in ("Factory Admin","Accountant/Auditor"):
            con.close(); flash("You cannot record payments.","warning"); return redirect(url_for("payments"))
        customer_id=int(request.form["customer_id"]); amount=to_paise(request.form["amount"])
        inv=con.execute("SELECT id FROM invoices WHERE order_id IN (SELECT id FROM orders WHERE customer_id=?) ORDER BY id DESC LIMIT 1",(customer_id,)).fetchone()
        con.execute("INSERT INTO payments(customer_id,invoice_id,amount_paise,paid_on,note) VALUES(?,?,?,?,?)",
                    (customer_id, inv["id"] if inv else None, amount,date.today().isoformat(),request.form.get("note","")))
        audit(con,"PAYMENT_RECORDED",f"Customer #{customer_id} paid {money(amount)}")
        con.commit(); flash("Payment recorded.","success")
    customers=con.execute("SELECT * FROM customers").fetchall()
    rows=con.execute("""SELECT p.*,c.name customer FROM payments p JOIN customers c ON c.id=p.customer_id ORDER BY p.id DESC""").fetchall()
    con.close()
    return render_template("payments.html",customers=customers,rows=rows)

@app.route("/production", methods=["GET","POST"])
@roles_required("Production Supervisor","Factory Admin")
def production():
    con=db()
    if request.method=="POST":
        planned=int(request.form.get("planned_qty",200)); actual=int(request.form.get("actual_qty",188))
        damaged=int(request.form.get("damaged_pouches",6)); cartons=int(request.form.get("cartons_used",9))
        labour=to_paise(request.form.get("labour","1200")); utilities=to_paise(request.form.get("utilities","600"))
        # Standard benchmark issue; form can change actual consumption.
        flour=float(request.form.get("flour","40")); oil=float(request.form.get("oil","10.5")); spice=float(request.form.get("spice","1.2"))
        issues=[("Flour",flour),("Oil",oil),("Spice mix",spice),("200g pouch",actual+damaged),("Carton",cartons)]
        insufficient=[f"{n}: need {q:g}, have {stock_material(con,n):g}" for n,q in issues if stock_material(con,n)+1e-9 < q]
        if insufficient:
            con.close(); flash("Cannot record production: "+"; ".join(insufficient),"danger"); return redirect(url_for("production"))
        for n,q in issues: add_move(con,"material",None,n,"PRODUCTION_ISSUE",q,"Production run")
        add_move(con,"product",1,"Murukku","PRODUCTION_IN",actual,"Production run")
        yield_pct=(actual-planned)/planned*100 if planned else 0
        con.execute("INSERT INTO production_runs(product_id,planned_qty,actual_qty,damaged_pouches,cartons_used,labour_paise,utilities_paise,yield_pct,created_at) VALUES(1,?,?,?,?,?,?,?,?)",
                    (planned,actual,damaged,cartons,labour,utilities,yield_pct,datetime.now().isoformat(timespec="seconds")))
        audit(con,"PRODUCTION_RECORDED",f"Planned {planned}; actual {actual}; yield variance {yield_pct:.2f}%")
        con.commit(); con.close()
        flash(f"Production recorded. Yield variance {yield_pct:.1f}% (alert threshold: ±3%).","success" if abs(yield_pct)<=3 else "warning")
        return redirect(url_for("production"))
    materials=con.execute("SELECT name,unit,rate_paise FROM materials").fetchall()
    runs=con.execute("SELECT * FROM production_runs ORDER BY id DESC LIMIT 10").fetchall()
    con.close()
    return render_template("production.html",materials=materials,runs=runs)

@app.route("/inventory")
@login_required
def inventory():
    con=db()
    materials=con.execute("SELECT * FROM materials").fetchall()
    material_rows=[{"name":m["name"],"unit":m["unit"],"qty":stock_material(con,m["name"]),"rate":m["rate_paise"]} for m in materials]
    product_qty=stock_product(con)
    ledger=con.execute("SELECT * FROM stock_movements ORDER BY id DESC LIMIT 25").fetchall()
    con.close()
    return render_template("inventory.html",materials=material_rows,product_qty=product_qty,ledger=ledger)

@app.route("/purchase", methods=["GET","POST"])
@roles_required("Production Supervisor","Factory Admin")
def purchase():
    con=db()
    if request.method=="POST":
        name=request.form["material"]; qty=float(request.form["quantity"]); rate=to_paise(request.form["rate"])
        m=con.execute("SELECT * FROM materials WHERE name=?",(name,)).fetchone()
        if not m: con.close(); flash("Unknown material.","danger"); return redirect(url_for("purchase"))
        add_move(con,"material",m["id"],name,"PURCHASE_IN",qty,"Purchase receipt")
        con.execute("UPDATE materials SET rate_paise=? WHERE id=?",(rate,m["id"]))
        audit(con,"PURCHASE_RECEIVED",f"{qty:g} {m['unit']} {name} at {money(rate)} per unit")
        con.commit(); con.close(); flash("Purchase receipt added to stock ledger.","success"); return redirect(url_for("inventory"))
    materials=con.execute("SELECT * FROM materials").fetchall()
    con.close()
    return render_template("purchase.html",materials=materials)

@app.route("/ai")
@login_required
def ai_insights():
    import pandas as pd
    from sklearn.linear_model import LinearRegression
    con=db()
    history=pd.read_sql_query("SELECT day,qty FROM sales_history ORDER BY day",con)
    actual_stock=stock_product(con)
    con.close()
    forecast=None; trend=None; diff=None; pct=None; recent_avg=None; note=None
    if len(history) >= 14:
        history["day_num"]=range(len(history))
        model=LinearRegression().fit(history[["day_num"]],history["qty"])
        next_day=len(history)
        forecast=max(0,int(round(float(model.predict(pd.DataFrame({"day_num":[next_day]}))[0]))))
        recent_avg=int(round(history.tail(7)["qty"].mean()))
        diff=forecast-recent_avg
        pct=(diff/recent_avg*100) if recent_avg else 0
        trend="Increasing" if model.coef_[0]>0.15 else ("Decreasing" if model.coef_[0]<-0.15 else "Stable")
        note="Linear regression trained on the seeded demo sales history. Replace demo observations with real daily sales to improve reliability."
    else:
        note="Not enough history yet. Add at least 14 daily sales observations before displaying a forecast."
    con=db()
    runs=con.execute("SELECT * FROM production_runs ORDER BY id DESC LIMIT 5").fetchall()
    con.close()
    return render_template("ai.html",forecast=forecast,recent_avg=recent_avg,diff=diff,pct=pct,trend=trend,note=note,history_count=len(history),stock=actual_stock,runs=runs)

@app.route("/reports")
@login_required
def reports():
    con=db()
    sales=con.execute("""SELECT i.invoice_no,c.name customer,o.quantity,i.taxable_paise,i.cgst_paise,i.sgst_paise,i.igst_paise,i.total_paise,i.created_at
                         FROM invoices i JOIN orders o ON o.id=i.order_id JOIN customers c ON c.id=o.customer_id ORDER BY i.id DESC""").fetchall()
    payments_total=con.execute("SELECT COALESCE(SUM(amount_paise),0) v FROM payments").fetchone()["v"]
    con.close()
    return render_template("reports.html",sales=sales,payments_total=payments_total)

@app.route("/export/sales.csv")
@roles_required("Owner","Factory Admin","Accountant/Auditor")
def export_sales():
    con=db()
    rows=con.execute("""SELECT i.invoice_no,c.name customer,c.state,o.quantity,i.taxable_paise,i.cgst_paise,i.sgst_paise,i.igst_paise,i.total_paise,i.created_at
                        FROM invoices i JOIN orders o ON o.id=i.order_id JOIN customers c ON c.id=o.customer_id ORDER BY i.id""").fetchall()
    con.close()
    output=io.StringIO(); w=csv.writer(output)
    w.writerow(["Invoice","Customer","State","Packets","Taxable (INR)","CGST (INR)","SGST (INR)","IGST (INR)","Total (INR)","Date"])
    for r in rows: w.writerow([r["invoice_no"],r["customer"],r["state"],r["quantity"],r["taxable_paise"]/100,r["cgst_paise"]/100,r["sgst_paise"]/100,r["igst_paise"]/100,r["total_paise"]/100,r["created_at"]])
    return Response(output.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=factoryflow_sales_register.csv"})

@app.route("/invoice/<int:invoice_id>.pdf")
@login_required
def invoice_pdf(invoice_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    con=db()
    row=con.execute("""SELECT i.*,o.quantity,c.name customer,c.state,c.gstin,p.name product,p.packet_size
                       FROM invoices i JOIN orders o ON o.id=i.order_id JOIN customers c ON c.id=o.customer_id JOIN products p ON p.id=1 WHERE i.id=?""",(invoice_id,)).fetchone()
    con.close()
    if not row: return "Invoice not found",404
    buf=io.BytesIO(); c=canvas.Canvas(buf,pagesize=A4)
    c.setFont("Helvetica-Bold",22); c.drawString(50,790,"FACTORYFLOW")
    c.setFont("Helvetica",11); c.drawString(50,765,"GST TAX INVOICE")
    c.drawString(50,735,f"Invoice: {row['invoice_no']}")
    c.drawString(50,715,f"Customer: {row['customer']}"); c.drawString(50,697,f"State: {row['state']}  GSTIN: {row['gstin']}")
    c.line(50,675,545,675)
    c.drawString(50,650,f"{row['product']} ({row['packet_size']})")
    c.drawString(50,630,f"Quantity: {row['quantity']} packets")
    c.drawString(50,600,f"Taxable value: {money(row['taxable_paise'])}")
    c.drawString(50,580,f"CGST: {money(row['cgst_paise'])}")
    c.drawString(50,560,f"SGST: {money(row['sgst_paise'])}")
    c.drawString(50,540,f"IGST: {money(row['igst_paise'])}")
    c.setFont("Helvetica-Bold",14); c.drawString(50,505,f"Invoice total: {money(row['total_paise'])}")
    c.setFont("Helvetica",9); c.drawString(50,460,"Demo invoice for internship evaluation. Validate statutory requirements before production use.")
    c.save(); buf.seek(0)
    return send_file(buf,as_attachment=True,download_name=f"{row['invoice_no']}.pdf",mimetype="application/pdf")

@app.route("/customers")
@login_required
def customers():
    con=db(); rows=con.execute("SELECT * FROM customers").fetchall(); con.close()
    return render_template("customers.html",rows=rows)

@app.route("/audit")
@roles_required("Owner","Accountant/Auditor","Factory Admin")
def audit_page():
    con=db(); rows=con.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 100").fetchall(); con.close()
    return render_template("audit.html",rows=rows)

@app.errorhandler(500)
def server_error(error):
    return render_template("error.html"),500

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
