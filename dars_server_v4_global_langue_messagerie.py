import os
import re
import html
import sqlite3
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, redirect, url_for, session, render_template_string, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash

APP_NAME = "DARS 🌍 4.0 GLOBAL"
DB_NAME = "dars_simple.db"
app = Flask(__name__)
app.secret_key = os.environ.get("DARS_SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=False, MAX_CONTENT_LENGTH=8 * 1024 * 1024)

COUNTRIES = ["Bénin", "Togo", "Nigeria", "Ghana", "Côte d'Ivoire", "Burkina Faso",
             "Niger", "Mali", "Sénégal", "Cameroun", "France", "Belgique", "Canada",
             "États-Unis", "Royaume-Uni", "Allemagne", "Espagne", "Portugal", "Brésil",
             "Maroc", "Afrique du Sud", "Kenya", "Inde", "Japon", "Australie"]
CURRENCIES = {
    "Bénin": ("XOF", "FCFA"), "Togo": ("XOF", "FCFA"),
    "Côte d'Ivoire": ("XOF", "FCFA"), "Burkina Faso": ("XOF", "FCFA"),
    "Niger": ("XOF", "FCFA"), "Sénégal": ("XOF", "FCFA"), "Mali": ("XOF", "FCFA"),
    "Nigeria": ("NGN", "₦"), "Ghana": ("GHS", "GH₵"),
    "France": ("EUR", "€"), "Belgique": ("EUR", "€"), "Allemagne": ("EUR", "€"),
    "Espagne": ("EUR", "€"), "Portugal": ("EUR", "€"),
    "Canada": ("CAD", "CA$"), "États-Unis": ("USD", "$"),
    "Royaume-Uni": ("GBP", "£"), "Brésil": ("BRL", "R$"),
    "Maroc": ("MAD", "د.م."), "Afrique du Sud": ("ZAR", "R"),
    "Kenya": ("KES", "KSh"), "Inde": ("INR", "₹"),
    "Japon": ("JPY", "¥"), "Australie": ("AUD", "A$")
}
LANGUAGES = {"fr": "Français", "en": "English", "es": "Español", "pt": "Português"}
TEXT = {
 "fr": {"home":"Accueil","feed":"Pour toi","premium":"Premium","create":"Créer une publicité","dashboard":"Tableau de bord","messages":"Messagerie","login":"Connexion","register":"Inscription","logout":"Déconnexion","language":"Langue","tagline":"La plateforme mondiale de publicité","send":"Envoyer"},
 "en": {"home":"Home","feed":"For you","premium":"Premium","create":"Create an ad","dashboard":"Dashboard","messages":"Messages","login":"Log in","register":"Sign up","logout":"Log out","language":"Language","tagline":"The global advertising platform","send":"Send"},
 "es": {"home":"Inicio","feed":"Para ti","premium":"Premium","create":"Crear anuncio","dashboard":"Panel","messages":"Mensajes","login":"Iniciar sesión","register":"Registrarse","logout":"Cerrar sesión","language":"Idioma","tagline":"La plataforma mundial de publicidad","send":"Enviar"},
 "pt": {"home":"Início","feed":"Para você","premium":"Premium","create":"Criar anúncio","dashboard":"Painel","messages":"Mensagens","login":"Entrar","register":"Cadastro","logout":"Sair","language":"Idioma","tagline":"A plataforma mundial de publicidade","send":"Enviar"}
}
PLANS = {"premium_mensuel": ("Premium mensuel", 2500, 30),
         "premium_annuel": ("Premium annuel", 25000, 365)}

def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def db():
    c = sqlite3.connect(DB_NAME)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            country TEXT NOT NULL DEFAULT 'Bénin', currency TEXT NOT NULL DEFAULT 'XOF',
            language TEXT NOT NULL DEFAULT 'fr', is_premium INTEGER NOT NULL DEFAULT 0,
            premium_until TEXT, created_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS ads(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            product TEXT NOT NULL, description TEXT NOT NULL, country TEXT NOT NULL,
            city TEXT, min_age INTEGER NOT NULL DEFAULT 13, max_age INTEGER NOT NULL DEFAULT 100,
            gender TEXT NOT NULL DEFAULT 'Tous', interests TEXT,
            daily_budget REAL NOT NULL DEFAULT 0, total_budget REAL NOT NULL DEFAULT 0,
            duration_days INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active',
            boosted INTEGER NOT NULL DEFAULT 0, impressions INTEGER NOT NULL DEFAULT 0,
            clicks INTEGER NOT NULL DEFAULT 0, likes INTEGER NOT NULL DEFAULT 0,
            shares INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)""")
        c.execute("""CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            amount REAL NOT NULL, currency TEXT NOT NULL, type TEXT NOT NULL,
            status TEXT NOT NULL, reference TEXT NOT NULL UNIQUE,
            description TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)""")
        c.execute("""CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
            read_at TEXT, FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE)""")
        c.execute("""CREATE TABLE IF NOT EXISTS security_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT NOT NULL,
            ip TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL)""")
        # Migrations for older DARS databases.
        cols = [r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()]
        for name, sql in [
            ("country", "ALTER TABLE users ADD COLUMN country TEXT NOT NULL DEFAULT 'Bénin'"),
            ("currency", "ALTER TABLE users ADD COLUMN currency TEXT NOT NULL DEFAULT 'XOF'"),
            ("language", "ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'fr'"),
            ("is_premium", "ALTER TABLE users ADD COLUMN is_premium INTEGER NOT NULL DEFAULT 0"),
            ("premium_until", "ALTER TABLE users ADD COLUMN premium_until TEXT")
        ]:
            if name not in cols:
                c.execute(sql)
init_db()

def user():
    uid = session.get("uid")
    if not uid:
        return None
    with db() as c:
        return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

def log_event(action, uid=None):
    with db() as c:
        c.execute("INSERT INTO security_logs(user_id,action,ip,created_at) VALUES(?,?,?,?)",
                  (uid, action, request.remote_addr, now()))

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]

def check_csrf():
    token = request.form.get("csrf", "")
    if not token or not secrets.compare_digest(token, session.get("csrf", "")):
        abort(400)

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("uid"):
            flash("Connecte-toi pour continuer.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped

def tr(key):
    lang = session.get("language", "fr")
    return TEXT.get(lang, TEXT["fr"]).get(key, TEXT["fr"].get(key, key))

def current_currency():
    u = user()
    if u:
        return u["currency"], CURRENCIES.get(u["country"], ("XOF", "FCFA"))[1]
    country = session.get("country", "Bénin")
    return CURRENCIES.get(country, ("XOF", "FCFA"))

def fmt_money(amount, currency=None):
    u = user()
    if not currency:
        currency = u["currency"] if u else current_currency()[0]
    symbol = next((v[1] for v in CURRENCIES.values() if v[0] == currency), currency)
    return f"{float(amount):,.0f} {symbol}".replace(",", " ")

def render_page(title, body):
    return render_template_string(BASE, title=title, body=body, csrf=csrf_token(),
                                  current_user=user(), tr=tr, languages=LANGUAGES,
                                  active_language=session.get("language", "fr"))

BASE = """
<!doctype html><html lang="{{ active_language }}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{{ title }} — DARS</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f3f5f9;color:#111827;font-family:Arial,sans-serif}
header{background:linear-gradient(135deg,#14366f,#1261d5);color:white;padding:22px 15px}
.logo{text-align:center;font-size:40px;font-weight:800}.nav{display:flex;flex-wrap:wrap;justify-content:center;gap:9px;margin-top:18px}
.nav a{color:white;text-decoration:none;padding:10px 13px;border-radius:12px;background:#ffffff20}
.container{max-width:900px;margin:25px auto;padding:0 15px}.card{background:white;border-radius:20px;padding:23px;margin:16px 0;box-shadow:0 7px 25px #0000000d}
h1,h2,h3{margin-top:0}input,textarea,select{width:100%;padding:13px;margin:7px 0 14px;border:1px solid #ccd2dc;border-radius:11px;font-size:16px}
textarea{min-height:100px}button,.btn{display:inline-block;border:0;border-radius:11px;padding:12px 17px;background:#1764d8;color:white;text-decoration:none;font-size:16px;cursor:pointer}
.green{background:#07884e}.gold{background:#c88a00}.gray{background:#56616f}.alert{padding:12px;border-radius:10px;margin:10px 0;background:#e9eef7}.success{background:#dff7e9}.warning{background:#fff3cd}.error{background:#ffe0e0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:13px}.stat{background:#eef4ff;border-radius:14px;padding:18px;text-align:center}.stat strong{display:block;font-size:25px}
.small{font-size:13px;color:#667085}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:9px;border-bottom:1px solid #ddd}footer{text-align:center;padding:25px;color:#667085}
</style></head><body><header><div class="logo">DARS 🌍</div><div style="text-align:center">{{ tr('tagline') }}</div>
<div class="nav"><a href="/">{{ tr('home') }}</a><a href="/feed">{{ tr('feed') }}</a><a href="/premium">{{ tr('premium') }}</a>
{% if current_user %}<a href="/create">{{ tr('create') }}</a><a href="/dashboard">{{ tr('dashboard') }}</a><a href="/messages">{{ tr('messages') }}</a><a href="/payments">💳 Paiements</a><a href="/logout">{{ tr('logout') }}</a>
{% else %}<a href="/login">{{ tr('login') }}</a><a href="/register">{{ tr('register') }}</a>{% endif %}
<a href="/language">🌐 {{ tr('language') }}</a></div></header>
<div class="container">{% with msgs=get_flashed_messages(with_categories=true) %}{% for cat,msg in msgs %}<div class="alert {{ cat }}">{{ msg }}</div>{% endfor %}{% endwith %}
{{ body|safe }}</div><footer>DARS 🌍 — Prototype — Paiements en mode test</footer></body></html>
"""

@app.route("/")
def home():
    body = """
    <div class="card"><h1>🌍 Bienvenue sur DARS</h1>
    <p>Crée, publie et analyse tes publicités à travers le monde.</p>
    <div class="grid"><a class="btn green" href="/create">📢 Créer une publicité</a>
    <a class="btn" href="/feed">🔥 Découvrir les publicités</a><a class="btn gold" href="/premium">⭐ Premium</a>
    <a class="btn" href="/messages">💬 Messagerie</a></div></div>
    <div class="card"><h2>Fonctionnalités</h2><p>🎯 Ciblage · 💰 Budget · 📊 Statistiques · 🚀 Boost · ⭐ Premium · 💳 Paiements test · 🌐 Langues · 💬 Messages privés</p></div>
    """
    return render_page("Accueil", body)

@app.route("/language", methods=["GET", "POST"])
def language():
    if request.method == "POST":
        check_csrf()
        lang = request.form.get("language", "fr")
        country = request.form.get("country", session.get("country", "Bénin"))
        if lang not in LANGUAGES or country not in COUNTRIES:
            abort(400)
        session["language"] = lang
        session["country"] = country
        uid = session.get("uid")
        if uid:
            currency = CURRENCIES.get(country, ("XOF", "FCFA"))[0]
            with db() as c:
                c.execute("UPDATE users SET language=?,country=?,currency=? WHERE id=?",
                          (lang, country, currency, uid))
        flash("Préférences mises à jour.", "success")
        return redirect(url_for("home"))
    lang_opts = "".join(f'<option value="{k}" {"selected" if session.get("language","fr")==k else ""}>{v}</option>' for k,v in LANGUAGES.items())
    country_opts = "".join(f'<option value="{html.escape(c)}" {"selected" if session.get("country","Bénin")==c else ""}>{html.escape(c)}</option>' for c in COUNTRIES)
    body = f"""<div class="card"><h1>🌐 Langue et pays</h1>
    <form method="post"><input type="hidden" name="csrf" value="{{{{ csrf }}}}">
    <label>Langue préférée</label><select name="language">{lang_opts}</select>
    <label>Pays de résidence</label><select name="country">{country_opts}</select>
    <p class="small">La devise proposée dépend du pays sélectionné. Les prix affichés sont indicatifs et les paiements sont simulés dans cette version.</p>
    <button>Enregistrer mes préférences</button></form></div>"""
    return render_page("Langue et pays", body)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        check_csrf()
        name = (request.form.get("name") or "").strip()[:80]
        email = (request.form.get("email") or "").strip().lower()[:160]
        password = request.form.get("password") or ""
        country = request.form.get("country", "Bénin")
        language = request.form.get("language", "fr")
        if len(name) < 2 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Nom ou adresse e-mail invalide.", "error")
        elif len(password) < 8:
            flash("Le mot de passe doit contenir au moins 8 caractères.", "error")
        elif country not in COUNTRIES or language not in LANGUAGES:
            flash("Pays ou langue invalide.", "error")
        else:
            currency = CURRENCIES.get(country, ("XOF", "FCFA"))[0]
            try:
                with db() as c:
                    cur = c.execute("INSERT INTO users(name,email,password_hash,country,currency,language,created_at) VALUES(?,?,?,?,?,?,?)",
                                    (name,email,generate_password_hash(password),country,currency,language,now()))
                    uid = cur.lastrowid
                session.clear(); session["uid"] = uid; session["csrf"] = secrets.token_urlsafe(32)
                session["language"] = language; session["country"] = country
                log_event("INSCRIPTION", uid)
                flash("Compte créé avec succès.", "success")
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                flash("Cet e-mail est déjà utilisé.", "error")
    country_opts = "".join(f'<option value="{html.escape(c)}">{html.escape(c)}</option>' for c in COUNTRIES)
    lang_opts = "".join(f'<option value="{k}">{v}</option>' for k,v in LANGUAGES.items())
    body = f"""<div class="card"><h1>📝 Inscription</h1><form method="post">
    <input type="hidden" name="csrf" value="{{{{ csrf }}}}">
    <label>Nom</label><input name="name" required maxlength="80">
    <label>E-mail</label><input type="email" name="email" required>
    <label>Mot de passe (8 caractères minimum)</label><input type="password" name="password" minlength="8" required>
    <label>Pays de résidence</label><select name="country">{country_opts}</select>
    <label>Langue préférée</label><select name="language">{lang_opts}</select><button>Créer mon compte</button></form></div>"""
    return render_page("Inscription", body)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        check_csrf()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        with db() as c:
            u = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not u or not check_password_hash(u["password_hash"], password):
            log_event("ECHEC_CONNEXION")
            flash("E-mail ou mot de passe incorrect.", "error")
        else:
            session.clear(); session["uid"] = u["id"]; session["csrf"] = secrets.token_urlsafe(32)
            session["language"] = u["language"]; session["country"] = u["country"]
            log_event("CONNEXION", u["id"])
            return redirect(url_for("dashboard"))
    body = """<div class="card"><h1>🔐 Connexion</h1><form method="post">
    <input type="hidden" name="csrf" value="{{ csrf }}"><label>E-mail</label><input name="email" type="email" required>
    <label>Mot de passe</label><input name="password" type="password" required><button>Se connecter</button></form></div>"""
    return render_page("Connexion", body)

@app.route("/logout")
def logout():
    uid = session.get("uid")
    if uid: log_event("DECONNEXION", uid)
    session.clear()
    return redirect(url_for("home"))

@app.route("/create", methods=["GET", "POST"])
@login_required
def create_ad():
    if request.method == "POST":
        check_csrf()
        product = (request.form.get("product") or "").strip()[:120]
        description = (request.form.get("description") or "").strip()[:1000]
        country = request.form.get("country", "Bénin")
        city = (request.form.get("city") or "").strip()[:100]
        gender = request.form.get("gender", "Tous")
        interests = (request.form.get("interests") or "").strip()[:300]
        try:
            min_age = int(request.form.get("min_age", 13)); max_age = int(request.form.get("max_age", 100))
            daily = float(request.form.get("daily_budget", 0)); total = float(request.form.get("total_budget", 0))
            duration = int(request.form.get("duration", 7))
        except ValueError:
            flash("Valeur numérique invalide.", "error"); return redirect(url_for("create_ad"))
        if not product or not description or country not in COUNTRIES or not (13 <= min_age <= max_age <= 100) or daily < 0 or total < 0 or not 1 <= duration <= 365:
            flash("Vérifie les champs et les budgets.", "error")
        else:
            with db() as c:
                c.execute("""INSERT INTO ads(user_id,product,description,country,city,min_age,max_age,gender,interests,daily_budget,total_budget,duration_days,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (session["uid"],product,description,country,city,min_age,max_age,gender,interests,daily,total,duration,now()))
            flash("Publicité enregistrée.", "success"); return redirect(url_for("dashboard"))
    countries = "".join(f'<option>{html.escape(c)}</option>' for c in COUNTRIES)
    body = f"""<div class="card"><h1>📢 Créer une publicité</h1><form method="post">
    <input type="hidden" name="csrf" value="{{{{ csrf }}}}">
    <label>Produit ou service</label><input name="product" required maxlength="120">
    <label>Description</label><textarea name="description" required maxlength="1000"></textarea>
    <label>Pays ciblé</label><select name="country">{countries}</select><label>Ville</label><input name="city">
    <div class="grid"><div><label>Âge minimum</label><input type="number" name="min_age" value="13" min="13" max="100"></div>
    <div><label>Âge maximum</label><input type="number" name="max_age" value="100" min="13" max="100"></div></div>
    <label>Genre</label><select name="gender"><option>Tous</option><option>Homme</option><option>Femme</option><option>Autre</option></select>
    <label>Centres d'intérêt</label><input name="interests" placeholder="Mode, beauté, technologie...">
    <label>Budget journalier</label><input type="number" name="daily_budget" min="0" value="0">
    <label>Budget total</label><input type="number" name="total_budget" min="0" value="5000">
    <label>Durée (jours)</label><input type="number" name="duration" min="1" max="365" value="7">
    <button class="green">Publier la publicité</button></form></div>"""
    return render_page("Créer une publicité", body)

@app.route("/feed")
def feed():
    q = (request.args.get("q") or "").strip()[:100]
    with db() as c:
        if q:
            ads = c.execute("""SELECT ads.*,users.name FROM ads JOIN users ON users.id=ads.user_id
            WHERE ads.status='active' AND (product LIKE ? OR description LIKE ? OR country LIKE ? OR city LIKE ?)
            ORDER BY boosted DESC,id DESC""", (f"%{q}%",)*4).fetchall()
        else:
            ads = c.execute("SELECT ads.*,users.name FROM ads JOIN users ON users.id=ads.user_id WHERE status='active' ORDER BY boosted DESC,id DESC").fetchall()
        for ad in ads:
            c.execute("UPDATE ads SET impressions=impressions+1 WHERE id=?", (ad["id"],))
    cards = ""
    for ad in ads:
        ctr = (ad["clicks"] / ad["impressions"] * 100) if ad["impressions"] else 0
        cards += f"""<div class="card"><h2>{html.escape(ad['product'])} {'🚀 BOOST' if ad['boosted'] else ''}</h2>
        <p>{html.escape(ad['description'])}</p><p>📍 {html.escape(ad['country'])} {html.escape(ad['city'] or '')}</p>
        <p class="small">Par {html.escape(ad['name'])} · 👁 {ad['impressions']} · clics {ad['clicks']} · CTR {ctr:.2f}%</p>
        <a class="btn" href="/click/{ad['id']}">Voir la publicité</a></div>"""
    if not cards: cards = '<div class="card"><h2>📭 Aucune publicité pour le moment</h2><a class="btn green" href="/create">Créer une publicité</a></div>'
    body = f'<div class="card"><h1>🔥 Pour toi</h1><form><input name="q" value="{html.escape(q)}" placeholder="Rechercher un produit"><button>Rechercher</button></form></div>' + cards
    return render_page("Pour toi", body)

@app.route("/click/<int:ad_id>")
def click_ad(ad_id):
    with db() as c:
        ad = c.execute("SELECT * FROM ads WHERE id=? AND status='active'", (ad_id,)).fetchone()
        if not ad: abort(404)
        c.execute("UPDATE ads SET clicks=clicks+1 WHERE id=?", (ad_id,))
    body = f'<div class="card"><h1>{html.escape(ad["product"])}</h1><p>{html.escape(ad["description"])}</p><p>📍 {html.escape(ad["country"])}</p><a class="btn" href="/feed">Retour au fil</a></div>'
    return render_page(ad["product"], body)

@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["uid"]
    with db() as c:
        ads = c.execute("SELECT * FROM ads WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
        totals = c.execute("SELECT COALESCE(SUM(impressions),0) impressions,COALESCE(SUM(clicks),0) clicks,COALESCE(SUM(likes),0) likes,COALESCE(SUM(shares),0) shares,COALESCE(SUM(total_budget),0) budget FROM ads WHERE user_id=?", (uid,)).fetchone()
        u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    ctr = totals["clicks"] / totals["impressions"] * 100 if totals["impressions"] else 0
    rows = ""
    for ad in ads:
        rows += f'<tr><td>{html.escape(ad["product"])}</td><td>{ad["impressions"]}</td><td>{ad["clicks"]}</td><td>{fmt_money(ad["total_budget"],u["currency"])}</td><td><a class="btn" href="/boost/{ad["id"]}">Boost</a></td></tr>'
    if not rows: rows = '<tr><td colspan="5">Aucune publicité.</td></tr>'
    body = f"""<div class="card"><h1>📊 Dashboard</h1><p>Bonjour {html.escape(u['name'])} · Pays : {html.escape(u['country'])} · Devise : {u['currency']}</p>
    <div class="grid"><div class="stat"><strong>{totals['impressions']}</strong>Impressions</div><div class="stat"><strong>{totals['clicks']}</strong>Clics</div>
    <div class="stat"><strong>{ctr:.2f}%</strong>CTR</div><div class="stat"><strong>{totals['likes']}</strong>Likes</div><div class="stat"><strong>{totals['shares']}</strong>Partages</div></div></div>
    <div class="card"><h2>Mes publicités</h2><div style="overflow:auto"><table><tr><th>Produit</th><th>Impressions</th><th>Clics</th><th>Budget</th><th>Action</th></tr>{rows}</table></div></div>"""
    return render_page("Dashboard", body)

@app.route("/boost/<int:ad_id>", methods=["GET", "POST"])
@login_required
def boost(ad_id):
    with db() as c:
        ad = c.execute("SELECT * FROM ads WHERE id=? AND user_id=?", (ad_id,session["uid"])).fetchone()
    if not ad: abort(404)
    if request.method == "POST":
        check_csrf()
        try: amount = float(request.form.get("amount",0))
        except ValueError: amount = 0
        if amount < 500:
            flash("Le Boost doit être d'au moins 500 unités.", "error")
        else:
            u = user(); ref = "TEST-" + secrets.token_hex(8).upper()
            with db() as c:
                c.execute("UPDATE ads SET boosted=1 WHERE id=? AND user_id=?", (ad_id,session["uid"]))
                c.execute("INSERT INTO transactions(user_id,amount,currency,type,status,reference,description,created_at) VALUES(?,?,?,?,?,?,?,?)",
                          (session["uid"],amount,u["currency"],"BOOST","TEST_SUCCESS",ref,f"Boost publicité #{ad_id}",now()))
            flash("Boost activé en mode test : aucun argent réel prélevé.", "success")
            return redirect(url_for("dashboard"))
    body = f'<div class="card"><h1>🚀 Booster {html.escape(ad["product"])}</h1><form method="post"><input type="hidden" name="csrf" value="{{{{ csrf }}}}"><label>Montant en {user()["currency"]}</label><input type="number" name="amount" min="500" value="1000"><button>Activer le Boost en test</button></form><p class="small">Aucun paiement réel n’est effectué.</p></div>'
    return render_page("Boost", body)

@app.route("/premium", methods=["GET"])
def premium():
    u = user()
    choices = ""
    for key,(name,price,days) in PLANS.items():
        choices += f'<option value="{key}">{name} — {fmt_money(price, u["currency"] if u else current_currency()[0])}</option>'
    if u:
        form = f'<form method="post" action="/premium/buy"><input type="hidden" name="csrf" value="{{{{ csrf }}}}"><select name="plan">{choices}</select><button class="gold">Activer en mode test</button></form>'
    else:
        form = '<a class="btn" href="/login">Connecte-toi pour continuer</a>'
    body = '<div class="card"><h1>⭐ DARS Premium</h1><p>Avantages prévus : statistiques avancées, options de Boost et outils publicitaires.</p>' + form + '<p class="small">Les prix affichés sont des exemples et les transactions sont simulées. Aucune devise n’est convertie automatiquement dans cette version.</p></div>'
    return render_page("Premium", body)

@app.route("/premium/buy", methods=["POST"])
@login_required
def buy_premium():
    check_csrf()
    plan = request.form.get("plan")
    if plan not in PLANS: abort(400)
    name, price, days = PLANS[plan]
    u = user()
    until = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    ref = "TEST-" + secrets.token_hex(8).upper()
    with db() as c:
        c.execute("UPDATE users SET is_premium=1,premium_until=? WHERE id=?", (until,session["uid"]))
        c.execute("INSERT INTO transactions(user_id,amount,currency,type,status,reference,description,created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (session["uid"],price,u["currency"],"PREMIUM","TEST_SUCCESS",ref,name,now()))
    flash("Premium activé en mode test. Aucun argent réel n'a été débité.", "success")
    return redirect(url_for("dashboard"))

@app.route("/payments")
@login_required
def payments():
    with db() as c:
        rows = c.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC", (session["uid"],)).fetchall()
    tr_rows = "".join(f'<tr><td>{r["created_at"]}</td><td>{html.escape(r["type"])}</td><td>{fmt_money(r["amount"],r["currency"])}</td><td>{r["status"]}</td><td>{r["reference"]}</td></tr>' for r in rows)
    if not tr_rows: tr_rows = '<tr><td colspan="5">Aucune transaction.</td></tr>'
    body = '<div class="card"><h1>💳 Historique des paiements</h1><p class="alert warning">Mode test uniquement : aucune carte ni Mobile Money n’est débité.</p><div style="overflow:auto"><table><tr><th>Date</th><th>Type</th><th>Montant</th><th>État</th><th>Référence</th></tr>' + tr_rows + '</table></div></div>'
    return render_page("Paiements", body)

@app.route("/messages")
@login_required
def messages():
    uid = session["uid"]
    with db() as c:
        people = c.execute("SELECT id,name,email FROM users WHERE id != ? ORDER BY name COLLATE NOCASE", (uid,)).fetchall()
    cards = "".join(f'<div class="card"><h3>{html.escape(p["name"])}</h3><p class="small">{html.escape(p["email"])}</p><a class="btn" href="/messages/{p["id"]}">💬 Ouvrir la conversation</a></div>' for p in people)
    if not cards: cards = '<div class="card"><p>Aucun autre compte pour le moment. Crée un deuxième compte de test pour essayer la messagerie.</p></div>'
    return render_page("Messagerie", '<div class="card"><h1>💬 Messagerie DARS</h1><p>Choisis un utilisateur pour ouvrir une conversation privée.</p></div>' + cards)

@app.route("/messages/<int:other_id>", methods=["GET", "POST"])
@login_required
def conversation(other_id):
    uid = session["uid"]
    if other_id == uid: abort(400)
    with db() as c:
        other = c.execute("SELECT id,name FROM users WHERE id=?", (other_id,)).fetchone()
    if not other: abort(404)
    if request.method == "POST":
        check_csrf()
        body = (request.form.get("body") or "").strip()[:2000]
        if not body:
            flash("Le message ne peut pas être vide.", "error")
        else:
            with db() as c:
                c.execute("INSERT INTO messages(sender_id,receiver_id,body,created_at) VALUES(?,?,?,?)", (uid,other_id,body,now()))
            log_event("MESSAGE_ENVOYE", uid)
            return redirect(url_for("conversation", other_id=other_id))
    with db() as c:
        c.execute("UPDATE messages SET read_at=? WHERE sender_id=? AND receiver_id=? AND read_at IS NULL", (now(),other_id,uid))
        msgs = c.execute("SELECT m.*,u.name AS sender_name FROM messages m JOIN users u ON u.id=m.sender_id WHERE (m.sender_id=? AND m.receiver_id=?) OR (m.sender_id=? AND m.receiver_id=?) ORDER BY m.id ASC LIMIT 300", (uid,other_id,other_id,uid)).fetchall()
    rendered = ""
    for m in msgs:
        mine = m["sender_id"] == uid
        bg = "#dff7e9" if mine else "#eef4ff"
        rendered += f'<div style="background:{bg};padding:12px;border-radius:12px;margin:10px 0;text-align:{"right" if mine else "left"}"><strong>{html.escape(m["sender_name"])}</strong><br>{html.escape(m["body"]).replace(chr(10),"<br>")}<div class="small">{m["created_at"]}</div></div>'
    if not rendered: rendered = "<p>Aucun message pour le moment. Écris le premier !</p>"
    page = f'<div class="card"><h1>💬 Conversation avec {html.escape(other["name"])}</h1><a href="/messages">← Retour</a><div style="margin-top:18px">{rendered}</div><form method="post"><input type="hidden" name="csrf" value="{{{{ csrf }}}}"><label>Message</label><textarea name="body" maxlength="2000" required placeholder="Écris ton message..."></textarea><button>{tr("send")} 💌</button></form></div>'
    return render_page("Conversation", page)

@app.route("/api/test")
def api_test():
    return {"success": True, "application": APP_NAME, "message": "Serveur DARS opérationnel", "database": DB_NAME}

@app.route("/api/countries")
def api_countries():
    return {"success": True, "countries": [{"name": c, "currency": CURRENCIES.get(c,("XOF","FCFA"))[0], "symbol": CURRENCIES.get(c,("XOF","FCFA"))[1]} for c in COUNTRIES]}

@app.errorhandler(404)
def not_found(error):
    return render_page("Introuvable", '<div class="card"><h1>Page introuvable</h1><a class="btn" href="/">Accueil</a></div>'), 404

if __name__ == "__main__":
    print("=" * 52)
    print("DARS 🌍 4.0 GLOBAL")
    print("Base de données :", DB_NAME)
    print("Accueil : http://127.0.0.1:5000")
    print("Test : http://127.0.0.1:5000/api/test")
    print("Pays et devises : http://127.0.0.1:5000/api/countries")
    print("Messagerie : http://127.0.0.1:5000/messages")
    print("Langue et pays : http://127.0.0.1:5000/language")
    print("=" * 52)
    app.run(host="0.0.0.0", port=5000, debug=False)
