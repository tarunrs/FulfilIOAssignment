import os
import random
import time
from flask import Flask, request, render_template, session, flash, redirect, \
    url_for, jsonify, copy_current_request_context
from flask_mail import Mail, Message
from celery import Celery
from celery import Task
from flask import has_request_context, make_response, request, g
import logging
from sqlalchemy import Column, String, Boolean
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import random
import urllib
from flask_sse import sse
from models import *

engine = create_engine('postgresql://fulfilio:fulfilio@localhost:5432/fulfilio')

Session = sessionmaker()
Session.configure(bind=engine)
sess = Session()
Base = declarative_base()

log = logging.getLogger('fulfilio')

app = Flask(__name__)

Base.metadata.create_all(engine)
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery

celery = make_celery(app)

app.config["REDIS_URL"] = "redis://localhost:6379/0"
app.register_blueprint(sse, url_prefix='/stream')


@celery.task(bind=True)
def insert_task(self, filename):
    engine = create_engine('postgresql://fulfilio:fulfilio@localhost:5432/fulfilio')
    Session = sessionmaker()
    Session.configure(bind=engine)
    i = 0
    data = open(filename).read()
    lines = data.split("\r\n")
    total = len(lines)
    sess = Session()
    for line in lines[1:]:
        elems = line.split(",")
        if len(elems) < 3:
            continue
        elems[1] = elems[1].lower()
        elems[2] = ",".join(elems[2:])
        is_active = True if random.random() < 0.2 else False
        prod = Product(sku=elems[1], name=elems[0], description=elems[2], is_active=is_active)
        sess.merge(prod)
        sess.commit()
        if i % 100 == 0:
            sse.publish({"message": "Processed "+ str(i) + " of " + str(total) + " records"}, type='greeting')
        self.update_state(state='PROGRESS',
                          meta={'current': i, 'total': total,
                                'status': "Processing"})
        i += 1
    return 


@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('index.html')


@app.route('/uploader', methods = ['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        f = request.files['file']
        f.save(f.filename)
        task = insert_task.delay(f.filename)
        return render_template("upload.html")


@app.route('/products', methods=['GET', 'POST'])
def products():
    cursor = request.args.get("cursor")
    sku =  request.args.get("sku")
    name =  request.args.get("name")
    description =  request.args.get("description")
    is_active =  request.args.get("is_active")
    sku = "" if sku == "None" else sku
    name = "" if name == "None" else name
    description= "" if description == "None" else description
    is_active= "" if is_active == "None" else is_active
    if not cursor:
        cursor = 0
    else:
        cursor = int(cursor)
    count = 10
    query = sess.query(Product)
    if sku and len(sku) > 0:
        query = query.filter(Product.sku==sku.strip())
    if name and len(name) > 0:
        query = query.filter(Product.name.ilike('%'+ name.strip() + '%'))
    if description and len(description) > 0:
        query = query.filter(Product.description.ilike('%'+ description.strip() + '%'))
    if is_active and len(is_active) > 0:
        if is_active == "Active":
            query = query.filter(Product.is_active==True)
        elif is_active == "Inactive":
            query = query.filter(Product.is_active==False)
    total = query.count()
    lines= []
    for instance in query.limit(count).offset(cursor):
        data = {"sku": instance.sku, "name": instance.name, "description": instance.description, "is_active": str(instance.is_active)}
        lines.append(data)
    params = { "cursor": "0", "sku": sku, "name": name, "description": description, "is_active": is_active }
    firstParams = urllib.urlencode(params)
    prevParams = None
    nextParams = None
    lastParams = None
    if not cursor == 0:
        cursorStr =  str(cursor - count)
        params = { "cursor": cursorStr, "sku": sku, "name": name, "description": description, "is_active": is_active }
        prevParams = urllib.urlencode(params)
    pageNav = str(cursor / count + 1) + " / " + str(total / count + 1)
    if not cursor >= total - count:
        cursorStr =  str(cursor + count)
        params = { "cursor": cursorStr, "sku": sku, "name": name, "description": description, "is_active": is_active }
        nextParams = urllib.urlencode(params)
    cursorStr =  str(total / count * count)
    params = { "cursor": cursorStr, "sku": sku, "name": name, "description": description, "is_active": is_active }
    lastParams = urllib.urlencode(params)
    return render_template("products.html", lines=lines, firstParams=firstParams, prevParams=prevParams, pageNav=pageNav, nextParams=nextParams, lastParams=lastParams, total=total)


@app.route('/edit', methods = ['GET',  'POST'])
def edit_record():
    if request.method == 'GET':
        sku = request.args.get("sku")
        query = sess.query(Product)
        prod = query.filter(Product.sku==sku.strip()).one()
        return render_template("edit.html", sku=prod.sku, name=prod.name, description=prod.description, is_active=prod.is_active)
    else:
        sku = request.form.get("sku")
        name = request.form.get("name")
        description = request.form.get("description")
        is_active= request.form.get("is_active")
        is_active = True if is_active == "Active" else False
        prod = Product(sku=sku, name=name, description=description, is_active=is_active)
        sess.merge(prod)
        sess.commit()
        return render_template("edit.html", post=True)


@app.route('/add', methods = ['GET',  'POST'])
def add_record():
    if request.method == 'POST':
        sku = request.form.get("sku")
        name = request.form.get("name")
        description = request.form.get("description")
        is_active= request.form.get("is_active")
        is_active = True if is_active == "Active" else False
        try:
            prod = Product(sku=sku, name=name, description=description, is_active=is_active)
            sess.merge(prod)
            sess.commit()
            return render_template("add.html", error=False, post=True)
        except Exception as e:
            return render_template("add.html", error=True, post=True)
    return render_template("add.html")


@app.route('/delete', methods = ['GET',  'POST'])
def delete_db():
    if request.method == 'POST':
        confirmation = request.form.get("confirmation")
        if confirmation == "yes":
            try:
                sess.query(Product).delete()
                sess.commit()
                return render_template("delete.html", confirmation=confirmation)
            except Exception as e:
                return render_template("delete.html", error="true")
    return render_template("delete.html"


if __name__ == '__main__':
    app.run(debug=True)
