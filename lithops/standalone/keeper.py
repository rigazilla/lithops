import json
import os
import time
import threading
import logging
from lithops.standalone.standalone import StandaloneHandler
from lithops.constants import STANDALONE_INSTALL_DIR, JOBS_DIR


logger = logging.getLogger(__name__)


class BudgetKeeper(threading.Thread):
    """
    BudgetKeeper class used to automatically stop the VM instance
    """
    def __init__(self, config):
        threading.Thread.__init__(self)
        self.last_usage_time = time.time()

        self.standalone_config = config
        self.auto_dismantle = config['auto_dismantle']
        self.soft_dismantle_timeout = config['soft_dismantle_timeout']
        self.hard_dismantle_timeout = config['hard_dismantle_timeout']
        self.exec_mode = config['exec_mode']

        self.jobs = {}

        vm_data_file = os.path.join(STANDALONE_INSTALL_DIR, 'access.data')
        with open(vm_data_file, 'r') as ad:
            vm_data = json.load(ad)

        self.instance_name = vm_data['instance_name']
        self.private_ip = vm_data['private_ip']
        self.instance_id = vm_data['instance_id']

        logger.debug("Starting BudgetKeeper for {} ({}), instance ID: {}"
                     .format(self.instance_name, self.private_ip, self.instance_id))

        self.sh = StandaloneHandler(self.standalone_config)
        self.vm = self.sh.backend.get_vm(self.instance_name)
        self.vm.private_ip = self.private_ip
        self.vm.instance_id = self.instance_id
        self.vm.delete_on_dismantle = False if 'master' in self.instance_name or \
            self.exec_mode == 'consume' else True

    def update_config(self, config):
        self.standalone_config.update(config)
        self.auto_dismantle = config['auto_dismantle']
        self.soft_dismantle_timeout = config['soft_dismantle_timeout']
        self.hard_dismantle_timeout = config['hard_dismantle_timeout']
        self.exec_mode = config['exec_mode']

    def run(self):
        runing = True
        jobs_running = False

        logger.debug("BudgetKeeper started")

        if self.auto_dismantle:
            logger.debug('Auto dismantle activated - Soft timeout: {}s, Hard Timeout: {}s'
                         .format(self.soft_dismantle_timeout,
                                 self.hard_dismantle_timeout))
        else:
            # If auto_dismantle is deactivated, the VM will be always automatically
            # stopped after hard_dismantle_timeout. This will prevent the VM
            # being started forever due a wrong configuration
            logger.debug('Auto dismantle deactivated - Hard Timeout: {}s'
                         .format(self.hard_dismantle_timeout))

        while runing:
            time_since_last_usage = time.time() - self.last_usage_time

            for job_key in self.jobs.keys():
                done = os.path.join(JOBS_DIR, job_key+'.done')
                if os.path.isfile(done):
                    self.jobs[job_key] = 'done'

            logger.debug(f"self.jobs: {self.jobs}")

            if len(self.jobs) > 0 and all(value == 'done' for value in self.jobs.values()) \
               and self.auto_dismantle:

                # here we need to catch a moment when number of running JOBS become zero.
                # when it happens we reset countdown back to soft_dismantle_timeout
                if jobs_running:
                    jobs_running = False
                    self.last_usage_time = time.time()

                time_since_last_usage = time.time() - self.last_usage_time

                time_to_dismantle = int(self.soft_dismantle_timeout - time_since_last_usage)
            else:
                time_to_dismantle = int(self.hard_dismantle_timeout - time_since_last_usage)
                jobs_running = True

            if time_to_dismantle > 0:
                logger.debug(f"Time to dismantle: {time_to_dismantle} seconds")
                check_interval = max(time_to_dismantle / 10, 1)
                time.sleep(check_interval)
            else:
                logger.debug("Dismantling setup")
                try:
                    self.vm.stop()
                    runing = False
                except Exception as e:
                    logger.debug(f"Dismantle error {e}")
