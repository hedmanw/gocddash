from gocddash.analysis import pipeline_fetcher, go_request, data_access
from gocddash.util import file_storage


def pull(pipeline_name, subsequent_pipelines, start, dry_run):
    latest_pipeline = data_access.get_highest_pipeline_count(pipeline_name)
    print("In pipeline: " + pipeline_name)
    max_pipeline_status, max_available_pipeline = go_request.get_max_pipeline_status(pipeline_name)
    print("Latest synced pipeline locally: " + str(latest_pipeline))
    print("Latest pipeline in GO: " + str(max_pipeline_status))
    print("Latest available pipeline: " + str(max_available_pipeline))

    pipeline_name, latest_pipeline, max_pipeline_status, subsequent_pipelines, start = assert_correct_input(
        pipeline_name, latest_pipeline, max_pipeline_status, subsequent_pipelines, max_available_pipeline, start=start)

    if not dry_run:
        fetch_pipelines(pipeline_name, latest_pipeline, max_pipeline_status, subsequent_pipelines, start)
        print("Done.")
    else:
        print("Dry run!")


def export(pipeline_name, path, dry_run):
    print("Saving as " + path)
    if not dry_run:
        file_storage.save_as_csv(pipeline_name, path)
        print("Done!")
    else:
        print("Dry run!")


def all_info():
    all_synced = data_access.get_synced_pipelines()
    print("I have these pipelines: ")
    print("Pipeline \t\tLocal \tIn Go")
    for pipeline in all_synced:
        print(pipeline[0] + "\t" + str(pipeline[1]) + "\t" + str(go_request.get_max_pipeline_status(pipeline[0])[1]))


def info(pipeline_name):
    latest_pipeline = data_access.get_highest_pipeline_count(pipeline_name)
    print("In pipeline: " + pipeline_name)
    print("Current pipeline counter in GO, latest available pipeline: " + str(
        go_request.get_max_pipeline_status(pipeline_name)))
    print("Latest synced pipeline locally: " + str(latest_pipeline))


def assert_correct_input(pipeline_name, latest_pipeline, max_pipeline_status, subsequent_pipelines,
                         max_available_pipeline, start):
    if start == 0 and latest_pipeline >= go_request.get_max_pipeline_status(pipeline_name)[1]:
        print("Latest pipeline (" + str(latest_pipeline) + ") = Max available pipeline (" + str(
            max_available_pipeline) + "). Database is up to date!")
        print("Terminating program.")
        raise SystemExit

    if start + subsequent_pipelines > max_pipeline_status:
        initial_subsequent_pipelines = subsequent_pipelines
        subsequent_pipelines = max_pipeline_status - start
        print("Max requested pipeline (" + str(start + initial_subsequent_pipelines) + ") > Max pipeline in GO (" + str(
            max_pipeline_status) + "). Fetching latest " + str(subsequent_pipelines) + " pipelines instead.")

    return pipeline_name, latest_pipeline, max_pipeline_status, subsequent_pipelines, start


def fetch_pipelines(pipeline_name, latest_pipeline, max_pipeline_status, subsequent_pipelines, start):
    offset, run_times = go_request.calculate_request(latest_pipeline, max_pipeline_status,
                                                     pipelines=subsequent_pipelines, start=start)
    pipeline_fetcher.download_and_store(pipeline_name, offset, run_times)
