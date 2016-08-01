from . import parse_cctray
from .data_access import get_connection
from .go_client import go_get_cctray


def get_previous_stage(current_stage):
    result = get_connection().fetch_previous_stage(current_stage.pipeline_name, current_stage.pipeline_counter, current_stage.stage_counter, current_stage.stage_name)
    if result:
        return StageFailureInfo(*result)
    else:
        return None


def get_current_stage(pipeline_name):
    result = get_connection().fetch_current_stage(pipeline_name)
    if result:
        return StageFailureInfo(*result)
    return None


def get_latest_passing_stage(pipeline_name):
    result = get_connection().fetch_latest_passing_stage(pipeline_name)
    if result:
        return StageFailureInfo(*result)
    else:
        return None


def get_first_synced_stage(pipeline_name):
    result = get_connection().fetch_first_synced(pipeline_name)
    if result:
        return StageFailureInfo(*result)
    else:
        return None


def create_stage(pipeline_instance, stage):
    get_connection().insert_stage(pipeline_instance.instance_id, stage)


def create_job(stage, job):
    get_connection().insert_job(stage.stage_id, job)


class PipelineInstance:
    def __init__(self, pipeline_name, pipeline_counter, trigger_message, instance_id):
        self.pipeline_name = pipeline_name
        self.pipeline_counter = pipeline_counter
        self.trigger_message = trigger_message
        self.instance_id = instance_id
        self.stages = {}


class Stage:
    def __init__(self, stage_name, approved_by, stage_result, stage_counter, stage_id, scheduled_date):
        self.stage_name = stage_name
        self.approved_by = approved_by
        self.stage_result = stage_result
        self.stage_counter = stage_counter
        self.stage_id = stage_id
        self.scheduled_date = scheduled_date

    def is_success(self):
        return self.stage_result == "Passed"


class StageFailureInfo:
    def __init__(self, pipeline_name, pipeline_counter, stage_counter, stage_id, stage_name, trigger_message, approved_by, result, failure_stage, responsible, description, scheduled_date):
        self.pipeline_name = pipeline_name
        self.pipeline_counter = pipeline_counter
        self.stage_id = stage_id
        self.stage_name = stage_name
        self.trigger_message = trigger_message
        self.approved_by = approved_by
        self.stage_counter = stage_counter
        self.failure_stage = failure_stage
        self.result = result
        self.responsible = responsible
        self.description = description
        self.scheduled_date = scheduled_date

    def is_success(self):
        return self.result == "Passed"

    def is_claimed(self):
        return self.responsible is not None


class Job:
    def __init__(self, job_id, stage_id, job_name, agent_uuid, scheduled_date, job_result, tests_run, tests_failed, tests_skipped):
        self.job_id = job_id
        self.stage_id = stage_id
        self.job_name = job_name
        self.agent_uuid = agent_uuid
        self.scheduled_date = scheduled_date
        self.job_id = job_id
        self.job_result = job_result
        self.tests_run = tests_run
        self.tests_failed = tests_failed
        self.tests_skipped = tests_skipped

    def is_success(self):
        return self.job_result == "Passed"


def get_pipeline_heads():
    result = get_connection().get_synced_pipeline_heads()
    return fold(result, StageFailureInfo, [])


class GraphData:
    def __init__(self, pipeline_name, pipeline_counter, stage_counter, stage_name, stage_result, job_name, scheduled_date, job_result, agent_name, tests_run, tests_failed, tests_skipped):
        self.pipeline_name = pipeline_name
        self.pipeline_counter = pipeline_counter
        self.stage_counter = stage_counter
        self.stage_name = stage_name
        self.stage_result = stage_result
        self.job_name = job_name
        self.scheduled_date = scheduled_date
        self.job_result = job_result
        self.agent_name = agent_name
        self.tests_run = tests_run
        self.tests_failed = tests_failed
        self.tests_skipped = tests_skipped


class EmbeddedChart:
    def __init__(self, chart, js_resources, css_resources, script, div):
        self.chart = chart
        self.js_resources = js_resources
        self.css_resources = css_resources
        self.script = script
        self.div = div


def get_graph_statistics(pipeline_name):
    result = get_connection().get_graph_statistics(pipeline_name)
    return fold(result, GraphData)


def get_graph_statistics_for_final_stages(pipeline_name):
    result = get_connection().get_graph_statistics_for_final_stages(pipeline_name)
    return fold(result, GraphData)


def get_job_to_display(stage_id):
    result = get_connection().get_jobs_by_stage_id(stage_id)
    if result:
        jobs = fold(result, Job)
        for job in jobs:
            if not job.is_success():
                return job
        return jobs[0]
    else:
        return None


def fold(rows, class_to_instantiate, default=None):
    if rows:
        return list(map(lambda row: class_to_instantiate(*row), rows))
    else:
        return default


def get_cctray_status():
    xml = go_get_cctray()
    project = parse_cctray.Projects(xml)
    return project