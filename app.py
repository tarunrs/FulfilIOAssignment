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
#celery = Celery("fulfilio-tasks", broker=app.config['CELERY_BROKER_URL'])
#celery.conf.update(app.config)

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


if __name__ == '__main__':
    app.run(debug=True)