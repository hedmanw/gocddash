import argparse
import getpass
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from inspect import getsourcefile
from os.path import abspath
from pathlib import Path

from flask import Flask, render_template, request, make_response, redirect, url_for, Blueprint, abort

sys.path.append(str(Path(abspath(getsourcefile(lambda: 0))).parents[1]))

from gocddash.util.pipeline_config import create_pipeline_config
from gocddash.analysis.go_client import go_get_pipeline_groups, go_get_pipeline_status, create_go_client
from gocddash.console_parsers.git_history_comparison import get_git_comparison
from gocddash.dash_board import failure_tip, pipeline_status
from gocddash.analysis.data_access import get_connection, create_connection
from gocddash.analysis.domain import get_previous_stage, get_current_stage, get_latest_passing_stage, \
    get_first_synced_stage, get_pipeline_heads, get_job_to_display, EmbeddedChart, get_cctray_status, \
    create_instance_claim, InstanceClaim, get_claims_for_unsynced_pipelines
from gocddash.dash_board.graph import create_job_test_html_graph, single_pipeline_html_graph, all_pipelines_html_graph
#from gocddash.dash_board.cc_tray_cache import create_cache, get_cache

group_of_pipeline = defaultdict(str)

# Use a blueprint to allow URLs to be prefixed through
# APPLICATION_ROOT without running the app as a
# sub-mounted WSGI environment. See
# http://stackoverflow.com/questions/18967441/add-a-prefix-to-all-flask-routes
gocddash = Blueprint('gocddash', __name__, static_folder='static')


def get_bootstrap_theme():
    theme = request.cookies.get('theme_cookie')
    return theme or 'superhero'


def get_footer():
    try:
        return open('footer.txt').read()
    except IOError:
        return '???'


@gocddash.route("/", methods=['GET'])
def dashboard():
    which = request.args.get('which', 'failing')
    project = get_cctray_status()
    progress_bar_data = get_progress_bar_data(project)
    groups = request.cookies.get(
        'checked_pipeline_groups_cookie', '').split(',')

    pipelines = project.select(
        which, groups=groups, group_map=group_of_pipeline)

    # previous_pipelines = get_cache().get_pipelines()
    finished_pipelines = []
    if which == 'failing':
        pipeline_names = [pipeline.name for pipeline in pipelines]
        # finished_pipelines = [pipeline for pipeline in previous_pipelines if pipeline.name not in pipeline_names]
        # new_failing_pipelines = [pipeline for pipeline in pipelines if pipeline not in previous_pipelines]
        # if new_failing_pipelines:
        #     for pipeline in new_failing_pipelines:
        #         finished_pipelines.append(pipeline)

    all_pipelines = project.select('all')
    unwanted_pipelines = []
    for name, group in group_of_pipeline.items():
        if group not in groups:
            unwanted_pipelines.append(name)

    finished_pipelines = [pipeline for pipeline in all_pipelines if
                          pipeline in finished_pipelines and pipeline.name not in unwanted_pipelines]

    for pipeline in pipelines:
        pipeline_name = pipeline.name
        message, whom = pipeline_is_paused(pipeline_name)
        if message:
            pipeline.status = 'Paused'
            pipeline.messages['PausedCause'].add(message)
        if whom:
            pipeline.messages['PausedBy'].add(whom)

    synced_pipelines = dict()
    for pipeline_head in get_pipeline_heads():
        synced_pipelines[pipeline_head.pipeline_name] = pipeline_head

    loose_claims = dict()  # Loose meaning that the pipelines are not synced - but they can still be claimed.
    for claim in get_claims_for_unsynced_pipelines():
        loose_claims[claim.pipeline_name] = claim

    return render_template('index.html',
                           go_server_url=app.config['PUBLIC_GO_SERVER_URL'],
                           pipelines=pipelines,
                           theme=get_bootstrap_theme(),
                           cols=app.config['PIPELINE_COLUMNS'],
                           now=datetime.now(),
                           footer=get_footer(),
                           synced_pipelines=synced_pipelines,
                           unsynced_claims=loose_claims,
                           progress_bar_data=progress_bar_data,
                           application_root=app.config['APPLICATION_ROOT'],
                           finished_pipelines=finished_pipelines)


def get_progress_bar_data(project):
    no_failing_pipelines = float(len(project.select("failing")))
    no_progress_pipelines = float(len(project.select("progress")))
    total_no_pipelines = float(len(project.select("all")))

    success_percentage = (total_no_pipelines - no_progress_pipelines) / total_no_pipelines * 100
    progress_percentage = (no_progress_pipelines - no_failing_pipelines) / total_no_pipelines * 100
    failing_percentage = no_failing_pipelines / total_no_pipelines * 100

    return [success_percentage, progress_percentage, failing_percentage]


@gocddash.app_errorhandler(500)
def internal_server_error(e):
    return render_template('500.html', statuscode=e, now=datetime.now(), footer=get_footer(),
                           theme=get_bootstrap_theme(), dashboard_link=url_for('gocddash.dashboard')), 500


@gocddash.app_errorhandler(404)
def page_not_found(e):
    return render_template('404.html', statuscode=e, dashboard_link=url_for('gocddash.dashboard'), now=datetime.now(),
                           footer=get_footer(), theme=get_bootstrap_theme()), 404


# Catches all errors - a bit too trigger happy
# @gocddash.app_errorhandler(Exception)
# def all_exception_handler(error):
#     return render_template('500.html', statuscode=error), 500


@gocddash.route("/select/", methods=['GET', 'POST'])
def select():
    all_pipeline_groups = get_all_pipeline_groups()
    # all_pipeline_groups is a list of
    # [ 'name', checked?, [pipelines names...] ]

    if request.method == 'POST':
        checked_pipeline_groups = list(request.form)
        response = redirect(url_for('gocddash.dashboard'), code=302)
        response.set_cookie('checked_pipeline_groups_cookie',
                            value=",".join(checked_pipeline_groups))
    else:
        checked_pipeline_groups = request.cookies.get(
            'checked_pipeline_groups_cookie', '').split(',')
        for i, pipeline_group in enumerate(all_pipeline_groups):
            if pipeline_group[0] in checked_pipeline_groups:
                all_pipeline_groups[i][1] = 'checked'
        template = render_template('select.html',
                                   go_server_url=app.config['PUBLIC_GO_SERVER_URL'],
                                   pipelinegroups=all_pipeline_groups,
                                   now=datetime.now(),
                                   theme=get_bootstrap_theme(),
                                   footer=get_footer(),
                                   application_root=app.config['APPLICATION_ROOT'])

        response = make_response(template)
    return response


@gocddash.route("/select_theme/", methods=['GET', 'POST'])
def select_theme():
    if request.method == 'POST':
        theme = request.form.get('theme_name')
        response = redirect(url_for('gocddash.select_theme'), code=302)
        response.set_cookie('theme_cookie',
                            value=theme or get_bootstrap_theme())
    else:
        template = render_template('select_theme.html',
                                   go_server_url=app.config['PUBLIC_GO_SERVER_URL'],
                                   now=datetime.now(),
                                   theme=get_bootstrap_theme(),
                                   footer=get_footer())
        response = make_response(template)
    return response


@gocddash.route("/reloadconfig", methods=['POST'])
def reload_config():
    create_pipeline_config()
    return "OK."


@gocddash.route("/claim", methods=['POST'])
def claim_instance():
    pipeline_name = request.form.get('pipelineName')
    pipeline_counter = request.form.get('pipelineCounter')
    responsible = request.form.get('responsible')
    description = request.form.get('description')
    if not responsible:
        abort(400, "Someone must be responsible.")
    create_instance_claim(InstanceClaim(pipeline_name, pipeline_counter, responsible, description))
    return "OK."


@gocddash.route("/stats", methods=['GET'])
def stats():
    all_pipelines_agent_graph = EmbeddedChart(
        *all_pipelines_html_graph("Historical agent success rate for all pipelines. "))

    template = render_template(
        'stats.html',  # Defined in the templates folder
        agent_graph=all_pipelines_agent_graph,
        go_server_url=app.config['PUBLIC_GO_SERVER_URL'],
        now=datetime.now(),
        theme=get_bootstrap_theme(),
        footer=get_footer(),
        application_root=app.config['APPLICATION_ROOT'],
    )

    return make_response(template)


@gocddash.route("/graphs/<pipeline_name>", methods=['GET'])
def graphs(pipeline_name):
    agent_graph = EmbeddedChart(*single_pipeline_html_graph(pipeline_name,
                                                            "Historical agent success rate for {} (last month)".format(
                                                                pipeline_name)))
    tests_run_graph = EmbeddedChart(
        *create_job_test_html_graph(pipeline_name, "Historical tests run for {} ".format(pipeline_name)))
    app_root = app.config['APPLICATION_ROOT']
    back_to_insights_link = app_root + "/insights/{}".format(pipeline_name)

    template = render_template(
        'graphs.html',  # Defined in the templates folder
        agent_graph=agent_graph,
        tests_run_graph=tests_run_graph,
        go_server_url=app.config['PUBLIC_GO_SERVER_URL'],
        now=datetime.now(),
        theme=get_bootstrap_theme(),
        footer=get_footer(),
        application_root=app.config['APPLICATION_ROOT'],
        back_link=back_to_insights_link
    )

    return make_response(template)


@gocddash.route("/insights/<pipeline_name>", methods=['GET'])
def insights(pipeline_name):
    current_stage = get_current_stage(pipeline_name)
    if current_stage is None:
        abort(500,
              "Database error. Have you tried syncing some pipelines using sync_pipelines.py? Current_stage is None.")
    current_status = pipeline_status.create_stage_info(current_stage)
    last_stage = get_previous_stage(current_stage)
    previous_status = pipeline_status.create_stage_info(last_stage)
    latest_passing_stage = get_latest_passing_stage(pipeline_name, current_stage.stage_name)
    stage_name_index = (get_connection().get_stage_order(pipeline_name)).index(current_stage.stage_name)

    git_history = []
    perpetrator_data = []

    if not current_stage.is_success():
        if latest_passing_stage is None:
            latest_passing_stage = get_first_synced_stage(pipeline_name)
        if not current_stage.pipeline_counter - latest_passing_stage.pipeline_counter == 1:
            perpetrator_data = get_git_comparison(pipeline_name, latest_passing_stage.pipeline_counter + 1,
                                                  latest_passing_stage.pipeline_counter,
                                                  app.config['PREFERRED_UPSTREAM'])

        git_history = get_git_comparison(pipeline_name, current_stage.pipeline_counter,
                                            latest_passing_stage.pipeline_counter, app.config['PREFERRED_UPSTREAM'])

    base_url = app.config['PUBLIC_GO_SERVER_URL']

    rerun_link = base_url + "pipelines/{}/{}/{}/{}".format(current_stage.pipeline_name,
                                                           current_stage.pipeline_counter,
                                                           current_stage.stage_name,
                                                           current_stage.stage_counter)
    log_link = base_url + "tab/build/detail/{}/{}/{}/{}/{}#tab-tests".format(
        current_stage.pipeline_name, current_stage.pipeline_counter, current_stage.stage_name,
        current_stage.stage_counter, get_job_to_display(current_stage.stage_id).job_name)

    main_pipeline_link = base_url + "tab/pipeline/history/{}".format(current_stage.pipeline_name)

    comparison_link = base_url + "compare/{}/{}/with/{}".format(current_stage.pipeline_name,
                                                                current_stage.pipeline_counter,
                                                                latest_passing_stage.pipeline_counter)

    dash_status = get_cctray_status()
    recommendation, last_claim = failure_tip.get_failure_tip(current_status, previous_status, latest_passing_stage.pipeline_counter)

    template = render_template(
        'insights.html',  # Defined in the templates folder
        go_server_url=app.config['PUBLIC_GO_SERVER_URL'],
        now=datetime.now(),
        theme=get_bootstrap_theme(),
        footer=get_footer(),
        current_status=current_status,
        git_history=git_history,
        rerun_link=rerun_link,
        comparison_link=comparison_link,
        live_info=dash_status.pipelines[pipeline_name],
        latest_passing_stage=latest_passing_stage,
        previous_status=previous_status,
        recommendation=recommendation,
        last_claim=last_claim,
        log_link=log_link,
        main_pipeline_link=main_pipeline_link,
        stage_name_index=stage_name_index,
        application_root=app.config['APPLICATION_ROOT'],
        username=app.config['GO_SERVER_USER'],
        passwd=app.config['GO_SERVER_PASSWD'],
        rerun_token=app.config['RERUN_TOKEN'],
        perpretrator_data=perpetrator_data
    )
    return make_response(template)


app = Flask(__name__)
app.config.from_pyfile('application.cfg', silent=False)
app.register_blueprint(gocddash, url_prefix=app.config["APPLICATION_ROOT"])


@app.template_filter('bootstrap_status')
def bootstrap_status(cctray_status):
    mapping = {
        'Failure': 'danger',
        'Building after Failure': 'warning',
        'Building after Success': 'info',
        'Success': 'success',
        'Paused': 'default',
    }
    return mapping.get(cctray_status, 'default')


@app.template_filter('rerun_valid')
def rerun_valid(rerun_status):
    if 'Building' in rerun_status:
        return "btn btn-lg btn-block"
    return "btn btn-primary btn-lg btn-block"


@app.template_filter('bootstrap_building')
def bootstrap_building(cctray_status):
    if 'Building' in cctray_status:
        return "progress-bar-striped"
    return ""


@app.template_filter('build_outcome')
def build_outcome(build_passed):
    return "text-success" if build_passed else "text-danger"


@app.template_filter('build_outcome_panel')
def build_outcome_panel(build_passed):
    return "success" if build_passed else "danger"


@app.template_filter('failure_stage')
def failure_stage(failure_stage):
    return "text-danger" if failure_stage else "text-warning"


@app.template_filter('building_panel_label')
def building_panel_label(cctray_status):
    if 'Building' in cctray_status:
        return "Building in Go"
    return "Latest in Go"


@app.template_filter('pluralize')
def pluralize(number, singular='', plural='s'):
    if number == 1:
        return singular
    else:
        return plural


@app.template_filter('time_or_date')
def time_or_date(timestamp):
    date_part, time_part = timestamp.split('T')
    if date_part == str(date.today()):
        return time_part
    return date_part


@app.template_filter('dt')
def _jinja2_filter_datetime(date_, fmt=None):
    if fmt:
        return date_.strftime(fmt)
    else:
        return date_.strftime('%Y-%m-%d')


@app.template_filter('tm')
def _jinja2_filter_datetime(datetime_, fmt=None):
    if fmt:
        return datetime_.strftime(fmt)
    else:
        return datetime_.strftime('%H:%M:%S')


@app.before_request
def setup():
    get_all_pipeline_groups()


def pipeline_is_paused(pipeline_name):
    if 'GO_SERVER_USER' in app.config:
        response = go_get_pipeline_status(pipeline_name)
        status = json.loads(response)
        if status["paused"]:
            return status.get("pausedCause") or 'Paused', status.get("pausedBy")
    return None, None


def get_all_pipeline_groups():
    kwargs = {}
    if 'GO_SERVER_USER' in app.config:
        kwargs['auth'] = (app.config['GO_SERVER_USER'], app.config['GO_SERVER_PASSWD'])
    json_text = go_get_pipeline_groups()
    full_json = json.loads(json_text)
    pipeline_groups = []
    for pipeline_group in full_json:
        pipeline_groups.append([pipeline_group['name'], '', []])
        for pipeline in pipeline_group['pipelines']:
            pipeline_groups[-1][-1].append(pipeline['name'])
            group_of_pipeline[pipeline['name']] = pipeline_group['name']
    return pipeline_groups


def is_valid_file(parser, arg):
    if not os.path.isfile(arg):
        parser.error("The file %s does not exist!" % arg)
    else:
        return open(arg, 'r')  # return an open file handle


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--go-server-url', help='go server url')
    parser.add_argument('-u', '--go-server-user', help='go server user name')
    parser.add_argument('-p', '--go-server-passwd', help='go server password')
    parser.add_argument('-d', '--debug', action='store_true')
    parser.add_argument('-c', '--pipeline-columns', type=int, choices=[1, 2, 3, 4],
                        default=app.config['PIPELINE_COLUMNS'], help="# columns in pipeline list")
    parser.add_argument('-b', '--bind-port', help='bind port')
    parser.add_argument('--db-port', help='database port')
    parser.add_argument('--pipeline-config', help='pipelines.json folder path')
    parser.add_argument('--file-client', help='file client folder path')
    pargs = parser.parse_args()
    pargs_dict = vars(pargs)
    app.config.update({key.upper(): pargs_dict[key] for key in pargs_dict if pargs_dict[key]})
    return pargs_dict


def main():
    gocddash_directory = os.path.dirname(abspath(getsourcefile(lambda: 0)))
    if not os.path.isfile(gocddash_directory + '/application.cfg'):
        print("Error: Missing application.cfg file in {}/".format(gocddash_directory))
        quit()
    pargs_dict = parse_args()
    if 'GO_SERVER_URL' not in app.config:
        app.config['GO_SERVER_URL'] = input('go-server url: ')
    if 'GO_SERVER_USER' not in app.config:
        app.config['GO_SERVER_USER'] = input('go-user: ')
    if 'GO_SERVER_PASSWD' not in app.config:
        app.config['GO_SERVER_PASSWD'] = getpass.getpass()

    create_connection(db_port=app.config['DB_PORT'])

    if pargs_dict['file_client']:
        create_go_client(pargs_dict['file_client'], auth=None)
    else:
        create_go_client(app.config['GO_SERVER_URL'], (app.config['GO_SERVER_USER'], app.config['GO_SERVER_PASSWD']))

    pipeline_path = pargs_dict['pipeline_config']
    create_pipeline_config(pipeline_path)

    # create_cache()


main()

if __name__ == '__main__':
    app.run(port=app.config['BIND_PORT'])
