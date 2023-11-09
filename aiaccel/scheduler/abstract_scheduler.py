from __future__ import annotations

from typing import Any

from omegaconf.dictconfig import DictConfig

from aiaccel.module import AbstractModule
from aiaccel.optimizer import AbstractOptimizer
from aiaccel.scheduler.job.job import Job
from aiaccel.scheduler.job.model.local_model import LocalModel
from aiaccel.util import Buffer, create_yaml


class AbstractScheduler(AbstractModule):
    """An abstract class for AbciScheduler and LocalScheduler.

    Args:
        options (dict[str, str | int | bool]): A dictionary containing
            command line options.

    Attributes:
        options (dict[str, str | int | bool]): A dictionary containing
            command line options.
            to select hyper parameters from a parameter pool.
        jobs (list[dict]): A list to store job dictionaries.
        num_workers (int): A max resource number.
        stats (list[dict]): A list of current status which is updated using ps
            command or qstat command.
    """

    def __init__(self, config: DictConfig, optimizer: AbstractOptimizer) -> None:
        super().__init__(config, "scheduler")
        self.set_logger(
            logger_name="root.scheduler",
            logfile=self.workspace.log / "scheduler.log",
            file_level=self.config.generic.logging_level,
            stream_level=self.config.generic.logging_level,
            module_type="Scheduler",
        )
        self.optimizer = optimizer
        self.num_workers = self.config.resource.num_workers
        self.trial_number = self.config.optimize.trial_number
        self.stats: list[Any] = []
        self.jobs: list[Any] = []
        self.job_status: dict[Any, Any] = {}
        self.start_trial_id = self.config.resume if self.config.resume is not None else 0
        self.buff = Buffer([trial_id for trial_id in range(self.start_trial_id, self.trial_number)])
        for trial_id in range(self.start_trial_id, self.config.optimize.trial_number):
            self.buff.d[trial_id].set_max_len(2)
        self.all_parameters_generated = False
        self.job_completed_count = 0

    def start_job(self, trial_id: int) -> Any:
        """Start a new job.

        Args:
            hp (Path): A parameter file path

        Returns:
            Job | None: A reference for created job. It returns None if
            specified hyper parameter file already exists.
        """
        trial_ids = [job.trial_id for job in self.jobs]
        if trial_id not in trial_ids:
            job = Job(self.config, self, self.create_model(), trial_id)
            self.jobs.append(job)
            self.logger.debug(f"submit a job: {str(trial_id)}")
            job.main()
            return job
        else:
            self.logger.error(f"Specified trial {trial_id} is already running ")
            return None

    def pre_process(self) -> None:
        """Pre-procedure before executing processes.

        Returns:
            None
        """
        self.write_random_seed_to_debug_log()
        self.resume()

    def post_process(self) -> None:
        """Post-procedure after executed processes.

        Returns:
            None
        """
        self.optimizer.finalize_operation()
        self.logger.info("scheduler finished.")

    def get_available_pool_size(self, num_ready: int, num_running: int, num_finished: int) -> None:
        sum_status = num_ready + num_running + num_finished
        if sum_status >= self.trial_number:
            return 0
        elif (self.trial_number - sum_status) < self.num_workers:
            return self.trial_number - sum_status
        else:
            return self.num_workers - num_running - num_ready

    def search_hyperparameters(self, num_ready: int, num_running: int, num_finished: int) -> None:
        """Start hyper parameter optimization.

        Returns:
            None
        """
        available_pool_size = self.get_available_pool_size(num_ready, num_running, num_finished)
        if available_pool_size == 0:
            return

        sum_status = num_ready + num_running + num_finished
        if sum_status >= self.trial_number and not self.all_parameters_generated:
            self.all_parameters_generated = True
            self.logger.info(
                f"trial_number: {self.trial_number}, \
                    ready: {num_ready}, running: {num_running}, finished: {num_finished} \
                    available pool size: {available_pool_size}"
            )
            self.logger.info("All parameters are generated.")
            return

        if not self.all_parameters_processed(num_ready, num_running) and not self.all_parameters_registered(
            num_ready, num_running, num_finished
        ):
            for _ in range(available_pool_size):
                self.optimizer.run_optimizer()

    def run_in_main_loop(self) -> bool:
        """A main loop process. This process is repeated every main loop.

        Returns:
            bool: The process succeeds or not. The main loop exits if failed.
        """

        num_ready, num_running, num_finished = self.storage.get_num_running_ready_finished()
        self.search_hyperparameters(num_ready, num_running, num_finished)
        if num_finished >= self.config.optimize.trial_number:
            return False

        readies = self.storage.state.get_ready()
        # find a new hp
        for ready in readies:
            if ready not in [job.trial_id for job in self.jobs]:
                self.start_job(ready)
                self.serialize(ready)

        for job in self.jobs:
            job.main()
            state_name = job.get_state_name()
            if state_name in {"success", "failure", "timeout"}:
                self.job_completed_count += 1
                self.jobs.remove(job)
                continue
            # Only log if the state has changed.
            if job.trial_id in self.buff.d.keys():
                self.buff.d[job.trial_id].add(state_name)
                if self.buff.d[job.trial_id].has_difference():
                    self.logger.info(f"name: {job.trial_id}, state: {state_name}")

        if self.trial_number == self.job_completed_count:
            self.logger.info("All jobs are completed.")
            return False
        return True

    def resume(self) -> None:
        """When in resume mode, load the previous optimization data in advance.

        Args:
            None

        Returns:
            None
        """
        if self.config.resume is not None and self.config.resume > 0:
            self.deserialize(self.config.resume)
            self.trial_number = self.config.optimize.trial_number

    def __getstate__(self) -> dict[str, Any]:
        obj = super().__getstate__()
        del obj["jobs"]
        del obj["optimizer"]
        return obj

    def create_model(self) -> Any:
        """Creates model object of state machine.

        Override with a Scheduler that uses a Model.
        For example, LocalScheduler, AbciScheduler, etc.
        By the way, PylocalScheduler does not use Model.

        Returns:
            LocalModel: LocalModel object.

            Should return None.
            For that purpose, it is necessary to modify TestAbstractScheduler etc significantly.
            So it returns LocalModel.

            # TODO: Fix TestAbstractScheduler etc to return None.
        """
        return LocalModel()

    def evaluate(self) -> None:
        """Evaluate the result of optimization.

        Returns:
            None
        """

        best_trial_ids, _ = self.storage.get_best_trial(self.goals)
        if best_trial_ids is None:
            self.logger.error(f"Failed to output {self.workspace.best_result_file}.")
            return
        hp_results = []
        for best_trial_id in best_trial_ids:
            hp_results.append(self.storage.get_hp_dict(best_trial_id))
        create_yaml(self.workspace.final_result_file, hp_results, self.workspace.lock)
        self.logger.info("Best hyperparameter is followings:")
        self.logger.info(hp_results)

    def all_parameters_processed(self, num_ready: int, num_running: int) -> bool:
        """Checks whether any unprocessed parameters are left.

        This method is beneficial for the case that the maximum number of
        parameter generation is limited by algorithm (e.g. grid search).
        To make this method effective, the algorithm with the parameter
        generation limit should turn `all_parameters_generated` True when all
        of available parameters are generated.

        Returns:
            bool: True if all parameters are generated and are processed.
        """
        return num_ready == 0 and num_running == 0 and self.all_parameters_generated

    def all_parameters_registered(self, num_ready: int, num_running: int, num_finished: int) -> bool:
        """Checks whether all parameters that can be generated with the given
        number of trials are registered.

        This method does not check whether the registered parameters have been
        processed.

        Returns:
            bool: True if all parameters are registerd.
        """
        return self.trial_number - num_finished - num_ready - num_running == 0
