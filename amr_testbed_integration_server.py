import datetime
import json
import time

import requests
from flask import Flask, jsonify, request

from testbed_config import (AMR, AMR_OFFBOARD_INFRA_REST_API_BASE_URL, PORT,
                            SENTINEL_DOCK_ID, TaskStatus, WorkCell,
                            parse_amr_resource_name_to_enum,
                            parse_location_name_to_enum,
                            TESTBED_EXECUTOR_SERVER_URL)

active_missions = {
    AMR.AMR_1: None,
    AMR.AMR_2: None,
}

testbed_executor_server_url=TESTBED_EXECUTOR_SERVER_URL

# creating a Flask app
app = Flask(__name__)


########### Helper functions ###########


# REST API call to AMR offboard infrastructure (backend) to create a new AMR mission
def create_new_amr_mission(amr, goal):
    data = {
        "status": TaskStatus.ENQUEUED.value,  # Set status to ENQUEUED using integer value
        "start": SENTINEL_DOCK_ID,  # Temporarily setting this to 0 as it is not currently used on the backend
        "goal": goal.value,  # Use integer value of the enum
        "enqueue_time": datetime.datetime.now().isoformat(),  # Set enqueue time to now
        # Leave the following fields null/empty
        "amr_id": amr.value,
        "material_transport_task_chain_id": None,
        "assembly_workflow_id": None,
        "start_time": None,
        "end_time": None,
    }

    url = f"{AMR_OFFBOARD_INFRA_REST_API_BASE_URL}/amrmissions/"
    headers = {"Content-Type": "application/json"}

    response = requests.post(url, data=json.dumps(data), headers=headers)

    return response


def parse_mission_request(mission):
    # Check if the mission is valid
    if mission["msgType"] != "StartTask" or len(mission['resources'])>1:
        return None
    # Check whether the mission contains an AMR resource
    matched_amr_resource = None
    for amr_resource_name in parse_amr_resource_name_to_enum.keys():
        if amr_resource_name in mission["resources"]:
            matched_amr_resource = parse_amr_resource_name_to_enum[amr_resource_name]
            break
    if matched_amr_resource is None:
        return None
    # Match goal location
    matched_goal_location = parse_location_name_to_enum[mission["location"]]

    return {
        "amr": matched_amr_resource,
        "goal": matched_goal_location,
    }


def generate_mission_completion_payload(amr):
    return {
        "msgType": "EndTask",
        "taskId": active_missions[amr]['taskId'],
        "name": active_missions[amr]['name'],
        "outcome": "success",
    }

# Flask Server Views

# Is called by the executor to enqueue a new AMR mission.
# Sample JSON request:
# {
#     "msgType": "StartTask",
#     "taskId": 1,
#     "name": "moveKitToArm",
#     "resources": [
#         "amr2"
#     ],
#     "structureType": “Heart",
#     "location": "Robot-Arm-2"
# }

@app.route("/execution", methods=["POST"])
def execution():
    # Get the mission from the executor
    potential_mission = request.get_json()
    mission_to_enqueue = parse_mission_request(potential_mission)

    if mission_to_enqueue is not None:
        create_new_amr_mission(mission_to_enqueue["amr"], mission_to_enqueue["goal"])
        active_missions[mission_to_enqueue["amr"]] = potential_mission
        print(
            f"{mission_to_enqueue['amr'].name} assigned a mission to go to {mission_to_enqueue['goal'].name}:\n {potential_mission}"
        )
        response_data = {'message': 'AMR mission created.'}
    else:
        response_data = {'message': 'AMR ignored the message'}
    return jsonify(response_data), 201

# Is called by the ROS offboard comms node to signal mission completion.
# This function forwards the mission completion signal to the executor.
# Sample json request received from the ROS offboard comms node:
# {
#     "amr": AMR.AMR_1,
# }
# Sample json POST request to send to the executor:
# {
#     "msgType": "EndTask",
#     "taskId": 1,
#     "name": "moveKitToArm",
#     "outcome": "success"
# }
@app.route("/forward_mission_completion", methods=["post"])
def forward_mission_completion():
    mission_completion_info = request.get_json()
    amr = mission_completion_info["amr"]
    
    print(request)
     
    print(active_missions)

    #print(f"{amr.name} has completed its mission.")
    executor_payload = generate_mission_completion_payload(
        AMR(mission_completion_info["amr"])
    )
    print("executor URL",testbed_executor_server_url) 
    print("responding to executor with: ", executor_payload)

    url = f"{testbed_executor_server_url}/execution"
    headers = {"content-type": "application/json"}
    time.sleep(10)
    requests.post(url, data=json.dumps(executor_payload), headers=headers)
    # todo[shobhit/zack]: it would be good style for the server to repond with acknowledgement of the mission completion

    # set amr's active mission to none
    active_missions[amr] = None

    response_data = {'message': 'forwarded mission completion signal to executor.'}
    return jsonify(response_data), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)
