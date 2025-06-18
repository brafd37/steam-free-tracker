import os
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from bs4 import BeautifulSoup
import atexit
from datetime import datetime

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///steam_tracker.db'
db = SQLAlchemy(app)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    webhook_url = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    check_interval = db.Column(db.Integer, default=10)

class History(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_type = db.Column(db.String(50))
    title = db.Column(db.String(200))
    url = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

scheduler = BackgroundScheduler()
sent_items = set()

def check_steam():
    with app.app_context():
        settings = Settings.query.first()
        if not settings or not settings.is_active:
            return
        check_games(settings.webhook_url)
        check_items(settings.webhook_url)

def check_games(webhook_url):
    try:
        url = "https://store.steampowered.com/search/?maxprice=free&specials=1"
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(response.text, 'html.parser')
        games = soup.select('#search_resultsRows a')
        for game in games:
            title_elem = game.select_one('.title')
            if not title_elem:
                continue
            title = title_elem.text.strip()
            game_url = game['href'].split('?')[0]
            game_id = game.get('data-ds-appid', '')
            if not game_id:
                continue
            if game_id not in sent_items:
                message = f"🎮 **Бесплатная игра!**\n{title}\n{game_url}"
                send_discord(webhook_url, message)
                sent_items.add(game_id)
                new_item = History(item_type="game", title=title, url=game_url)
                db.session.add(new_item)
                db.session.commit()
    except Exception as e:
        print(f"Ошибка в играх: {e}")

def check_items(webhook_url):
    try:
        url = "https://store.steampowered.com/points/shop"
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.select('.pointsshop_item')
        for item in items:
            if "Бесплатно" in item.text:
                title_elem = item.select_one('.item_name')
                if not title_elem:
                    continue
                title = title_elem.text.strip()
                link_elem = item.select_one('a')
                if not link_elem or not link_elem.get('href'):
                    continue
                item_url = "https://store.steampowered.com" + link_elem['href']
                if title not in sent_items:
                    message = f"✨ **Бесплатное украшение!**\n{title}\n{item_url}"
                    send_discord(webhook_url, message)
                    sent_items.add(title)
                    new_item = History(item_type="item", title=title, url=item_url)
                    db.session.add(new_item)
                    db.session.commit()
    except Exception as e:
        print(f"Ошибка в украшениях: {e}")

def send_discord(webhook_url, message):
    try:
        requests.post(webhook_url, json={"content": message})
    except:
        pass

@app.route('/')
def index():
    settings = Settings.query.first()
    history = History.query.order_by(History.timestamp.desc()).limit(10).all()
    stats = {
        'games': History.query.filter_by(item_type="game").count(),
        'items': History.query.filter_by(item_type="item").count()
    }
    return render_template('index.html', settings=settings, history=history, stats=stats)

@app.route('/update', methods=['POST'])
def update_settings():
    settings = Settings.query.first()
    if not settings:
        settings = Settings()
    settings.webhook_url = request.form['webhook_url']
    settings.is_active = 'is_active' in request.form
    check_interval = request.form.get('check_interval')
    if check_interval and check_interval.isdigit():
        settings.check_interval = int(check_interval)
    db.session.add(settings)
    db.session.commit()
    restart_scheduler(settings)
    return redirect(url_for('index'))

def restart_scheduler(settings):
    scheduler.remove_all_jobs()
    if settings and settings.is_active:
        scheduler.add_job(
            func=check_steam,
            trigger='interval',
            minutes=settings.check_interval,
            id='steam_check'
        )

if not scheduler.running:
    scheduler.start()
    settings = Settings.query.first()
    if settings and settings.is_active:
        restart_scheduler(settings)
    atexit.register(lambda: scheduler.shutdown())

if __name__ == '__main__':
    app.run()