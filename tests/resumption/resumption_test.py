from tests.integration.integration_test import IntegrationTest
from aiaccel.storage.storage import Storage
import subprocess
from aiaccel.config import Config
from pathlib import Path

class ResumptionTest(IntegrationTest):
    search_algorithm = None

    def test_run(self, cd_work, data_dir, work_dir):
        with self.create_main():
            config_file = data_dir.joinpath('config_{}.json'.format(self.search_algorithm))
            config = Config(config_file)
            storage = Storage(ws=Path(config.workspace.get()), fsmode=False, config_path=Path(config_file))
            subprocess.Popen(['aiaccel-start', '--config', str(config_file), '--clean']).wait()
            final_result_at_one_time = self.get_final_result(storage)
            print('at one time', final_result_at_one_time)

        # max trial 5
        with self.create_main():
            config_file = data_dir / f'config_{self.search_algorithm}_resumption.json'
            subprocess.Popen(['aiaccel-start', '--config', str(config_file), '--clean']).wait()

        # resume
        with self.create_main():
            config_file = data_dir.joinpath(f'config_{self.search_algorithm}.json')
            storage = Storage(ws=Path(config.workspace.get()), fsmode=False, config_path=Path(config_file))
            subprocess.Popen(['aiaccel-start', '--config', str(config_file), '--resume', '4']).wait()
            final_result_resumption = self.get_final_result(storage)
            print('resumption steps finished', final_result_resumption)
        
        assert final_result_at_one_time == final_result_resumption

    def get_final_result(self, storage):
        data = storage.result.get_all_result()
        return [d.objective for d in data][-1]
