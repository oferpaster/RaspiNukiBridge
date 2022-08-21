import asyncio
import os
import random

import json
import yaml
from nacl.public import PrivateKey

from consts import CONF_FILE_NAME, ADDON_CONF_FILE_NAME, DATA_PATH
from nuki import NukiManager, Nuki
from scan_ble import find_ble_device
from utils import logger


def get_config_file():
    if os.path.isdir(DATA_PATH):
        return os.path.join(DATA_PATH, CONF_FILE_NAME)
    return CONF_FILE_NAME

def get_addon_config_file():
    if os.path.isdir(DATA_PATH):
        return os.path.join(DATA_PATH, ADDON_CONF_FILE_NAME)
    return ADDON_CONF_FILE_NAME


def init_config(config_file, addon_config_file):
    if os.path.isfile(config_file):
        with open(config_file) as f:
            data = yaml.load(f, Loader=yaml.FullLoader)
            token = data["server"]["token"]
    else:
        app_id, token = _random_app_id_and_token()
        data = {
            'server': {
                'host': '0.0.0.0',
                'port': '8080',
                'adapter': 'hci1',
                'name': 'RaspiNukiBridge',
                'app_id': app_id,
                'token': token
            }
        }
    if os.path.isfile(addon_config_file):
        with open(addon_config_file) as f:
            addon_data = json.load(f)
    else:
        addon_data = {}
    global global_retry
    global global_connection_timeout
    global global_command_timeout
    if "adapter" in addon_data:
        data["server"]["adapter"] = addon_data["adapter"]
    if "retry" in addon_data:
        global_retry = addon_data["retry"]
    if "connection_timeout" in addon_data:
        global_connection_timeout = addon_data["connection_timeout"]
    if "command_timeout" in addon_data:
       global_command_timeout = addon_data["command_timeout"]
    name = data["server"]["name"]
    app_id = data["server"]["app_id"]
    bt_adapter = data["server"].get("adapter", "hci1")
    nuki_manager = NukiManager(name, app_id, bt_adapter)

    if 'smartlock' in data:
        for smartlock in data['smartlock']:
            if global_retry:
                smartlock["retry"] = global_retry
            if global_connection_timeout:
                smartlock["connection_timeout"] = global_connection_timeout
            if global_command_timeout:
                smartlock["command_timeout"] = global_command_timeout
        logger.info(f"********************************************************************")
        logger.info(f"*                                                                  *")
        logger.info(f"*                            Access Token                          *")
        logger.info(f"* {data['server']['token']} *")
        logger.info(f"*                                                                  *")
        logger.info(f"********************************************************************")
        return nuki_manager, data

    # Bridge keys
    bridge_public_key, bridge_private_key = _generate_bridge_keys()
    smartlock = {
        'bridge_public_key': bridge_public_key.hex(),
        'bridge_private_key': bridge_private_key.hex(),
        'connection_timeout': 10,
        'command_timeout': 30,
        'retry': 5
    }
    if global_retry:
        smartlock["retry"] = global_retry
    if global_connection_timeout:
        smartlock["connection_timeout"] = global_connection_timeout
    if global_command_timeout:
        smartlock["command_timeout"] = global_command_timeout

    # Device MAC Address
    nuki_devices = find_ble_device('Nuki_.*', logger)
    if len(nuki_devices) > 1:
        for device in nuki_devices:
            logger.info(device)
        raise ValueError('Multiple Nuki devices found. Please use --pair [MAC_ADDRESS]')
    if not nuki_devices:
        raise ValueError('No Nuki device found')
    address = nuki_devices[0].address

    smartlock['address'] = address

    # Pair
    nuki = Nuki(address, None, None, bridge_public_key, bridge_private_key)
    nuki_manager.add_nuki(nuki)

    loop = asyncio.new_event_loop()

    nuki_manager.start(loop)

    def pairing_completed(paired_nuki):
        nuki_public_key = paired_nuki.nuki_public_key.hex()
        auth_id = paired_nuki.auth_id.hex()
        logger.info(f"Pairing completed, auth_id: {auth_id}")
        logger.info(f"nuki_public_key: {nuki_public_key}")
        logger.info(f"********************************************************************")
        logger.info(f"*                                                                  *")
        logger.info(f"*                         Pairing completed!                       *")
        logger.info(f"*                            Access Token                          *")
        logger.info(f"* {token} *")
        logger.info(f"*                                                                  *")
        logger.info(f"********************************************************************")
        smartlock['nuki_public_key'] = nuki_public_key
        smartlock['auth_id'] = auth_id

        data['smartlock'] = [smartlock]
        yaml.dump(data, open(config_file, 'w'))
        loop.stop()

    loop.create_task(nuki.pair(pairing_completed))
    loop.run_forever()

    return nuki_manager, data


def _random_app_id_and_token():
    app_id = random.getrandbits(32)
    token = random.getrandbits(256).to_bytes(32, "little").hex()
    logger.info(f'Access Token: {token}')
    logger.info(f'app_id: {app_id}')
    return app_id, token


def _generate_bridge_keys():
    logger.info(f"Generating new keys")
    keypair = PrivateKey.generate()
    bridge_public_key = keypair.public_key.__bytes__()
    bridge_private_key = keypair.__bytes__()
    logger.info(f"bridge_public_key: {bridge_public_key.hex()}")
    logger.info(f"bridge_private_key: {bridge_private_key.hex()}")
    return bridge_public_key, bridge_private_key
