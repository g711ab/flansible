import platform

#Visual studio remote debugger
if platform.node() == 'ansible01':
    try:
        import ptvsd
        ptvsd.enable_attach(secret='my_secret', address = ('0.0.0.0', 3000))
    except:
        pass

import os
from datetime import datetime
from flask import render_template
from celery import Celery
import subprocess
import time
from flask_restful import Resource, Api
from ConfigParser import SafeConfigParser
from flask import Flask, request, render_template, session, flash, redirect, url_for, jsonify
from flask_httpauth import HTTPBasicAuth
from celery import Celery
import subprocess
import time
from flask_restful import Resource, Api, reqparse, fields
from flask_restful_swagger import swagger
import sys
from ModelClasses import AnsibleCommandModel, AnsibleRequestResultModel, AnsibleExtraArgsModel



app = Flask(__name__)
auth = HTTPBasicAuth()


config = SafeConfigParser()
config.read('config.ini')

app.config['CELERY_BROKER_URL'] = config.get("Default", "CELERY_BROKER_URL")
app.config['CELERY_RESULT_BACKEND'] = config.get("Default", "CELERY_RESULT_BACKEND")

api = swagger.docs(Api(app), apiVersion='0.1')

celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)



@auth.verify_password
def verify_password(username, password):
    result = False
    if username == config.get("Default", "username"):
        if password == config.get("Default", "password"):
            result = True
    return result

class RunAnsibleCommand(Resource):
    @swagger.operation(
        notes='Run ad-hoc Ansible command',
        nickname='ansiblecommand',
        responseClass=AnsibleRequestResultModel.__name__,
        parameters=[
            {
              "name": "body",
              "description": "Inut object",
              "required": True,
              "allowMultiple": False,
              "dataType": AnsibleCommandModel.__name__,
              "paramType": "body"
            }
          ],
        responseMessages=[
            {
              "code": 200,
              "message": "Ansible command started"
            },
            {
              "code": 400,
              "message": "Invalid input"
            }
          ]
    )
    @auth.login_required
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('module', type=str, help='module name', required=True)
        parser.add_argument('module_args', type=dict, help='module_args', required=False)
        parser.add_argument('extra_vars', type=dict, help='extra_vars', required=False)
        parser.add_argument('inventory', type=str, help='host filter/inventory', required=False)
        parser.add_argument('forks', type=int, help='forks', required=False)
        parser.add_argument('verbose_level', type=int, help='verbose level, 1-4', required=False)
        parser.add_argument('become', type=bool, help='run with become', required=False)
        parser.add_argument('become_method', type=str, help='become method', required=False)
        parser.add_argument('become_user', type=str, help='become user', required=False)
        args = parser.parse_args()
        req_module = args['module']
        module_args = args['module_args']
        extra_vars = args['extra_vars']
        host_filter = args['inventory']
        forks = args['forks']
        verbose_level = args['verbose_level']
        become = args['become']
        become_method = args['become_method']
        become_user = args['become_user']
        module_args_string = ''
        if module_args:
            counter = 1
            module_args_string += '-a"'
            for key in module_args.keys():
                if counter < len(module_args):
                    spacer = " "
                else:
                    spacer = ""
                opt_string = str.format("{0}={1}{2}",key,module_args[key], spacer)
                module_args_string += opt_string
                counter += 1
            module_args_string += '"'
        if not host_filter:
            host_filter = "localhost"
        if forks:
            fork_string = str.format('-f {0}', str(forks))
        else:
            fork_string = ''

        if verbose_level and verbose_level != 0:
            verb_counter = 1
            verb_string = " -"
            while verb_counter <= verbose_level:
                verb_string += "v"
                verb_counter += 1
        else:
            verb_string = ''

        if become:
            become_string = ' --become'
        else:
            become_string = ''

        if become_method:
            become_method_string = str.format(' --become-method={0}', become_method)
        else:
            become_method_string = ''

        if become_user:
            become_user_string = str.format(' --become-user={0}', become_user)
        else:
            become_user_string = ''


        command = str.format("ansible -m {0} {1} {2} {3}{4}{5}{6}{7}", req_module, module_args_string, fork_string, host_filter, verb_string, 
                             become_string, become_method_string, become_user_string)
        task_result = do_long_running_task.apply_async([command])
        result = {'task_id': task_result.id}
        return result

api.add_resource(RunAnsibleCommand, '/api/ansiblecommand')


class RunAnsiblePlaybook(Resource):
    @auth.login_required
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('playbook_dir', type=str, help='folder where playbook file resides', required=True)
        parser.add_argument('playbook', type=str, help='name of the playbook', required=True)
        parser.add_argument('extra_vars', type=dict, help='extra vars', required=False)
        parser.add_argument('forks', type=int, help='forks', required=False)
        parser.add_argument('verbose_level', type=int, help='verbose level, 1-4', required=False)

api.add_resource(RunAnsiblePlaybook, '/api/ansibleplaybook')
    

class AnsibleTaskStatus(Resource):
    @auth.login_required
    def get(self, task_id):
        task = do_long_running_task.AsyncResult(task_id)
        
        if task.state == "PROGRESS":
            result = "Task in progress"
        else:
            result = task.info['result']
        #result_out = task.info.replace('\n', "<br>")
        #result = result.replace('\n', '<br>')
        #return result, 200, {'Content-Type': 'text/html; charset=utf-8'}
        resp = app.make_response((result, 200))
        resp.headers['content-type'] = 'text/plain'
        return resp

api.add_resource(AnsibleTaskStatus, '/api/ansibletaskoutput/<string:task_id>')

@celery.task(bind=True)
def do_long_running_task(self, cmd):
    with app.app_context():
        error_out = None
        result = None
        self.update_state(state='PROGRESS',
                          meta={'result': result})
        try:
            result = subprocess.check_output([cmd], shell=True, stderr=error_out)
        except Exception as e:
            error_out = str(e)

        self.update_state(state='FINISHED',
                          meta={'result': error_out})
        if error_out:
            #failure
            self.update_state(state='FAILED',
                          meta={'result': error_out})
            return {'result': error_out}
        else:
            return {'result': result}

if __name__ == '__main__':
    app.run(debug=True, host=config.get("Default", "Flask_tcp_ip"), use_reloader=False, port=int(config.get("Default", "Flask_tcp_port")))