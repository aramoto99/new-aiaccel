from __future__ import annotations

from omegaconf.dictconfig import DictConfig
from scipy.stats import qmc

from aiaccel.converted_parameter import ConvertedParameterConfiguration
from aiaccel.optimizer import AbstractOptimizer


class SobolOptimizer(AbstractOptimizer):
    """An optimizer class with sobol algorithm.

    Args:
        config (DictConfig): A DictConfig object which has contents of
            configuration file and command line options.

    Attributes:
        sampler (Sobol): Engine for generating (scrambled) Sobol' sequences.

    Todo:
        Make it clear to resume this optimizer with Sobol sampler. Currentcode
        resume the sampler counts with a number of FINISHED PARAMETER FILES.
        Confirm whether the current code resumes for any timings of quits.
    """

    def __init__(self, config: DictConfig) -> None:
        super().__init__(config)
        self.sampler = qmc.Sobol(
            d=len(self.params.get_parameter_list()), scramble=self.config.optimize.sobol_scramble, seed=self._rng
        )
        self.params: ConvertedParameterConfiguration = ConvertedParameterConfiguration(self.params)

    def generate_parameter(self) -> list[dict[str, float | int | str]]:
        """Generate parameters.

        Returns:
            list[dict[str, float | int | str]]: A list of new parameters.
        """
        l_params = self.params.get_parameter_list()
        n_params = len(l_params)

        new_params = []
        vec = self.sampler.random()[0]

        for i in range(0, n_params):
            min_value = l_params[i].lower
            max_value = l_params[i].upper
            value = (max_value - min_value) * vec[i] + min_value
            new_param = {"name": l_params[i].name, "type": l_params[i].type, "value": value}
            new_params.append(new_param)

        return new_params

    def generate_initial_parameter(self) -> list[dict[str, float | int | str]]:
        """Generate initial parameters.

        Returns:
            list[dict[str, float | int | str]]: A list of new parameters.
        """

        for hyperparameter in self.params.get_parameter_list():
            if hyperparameter.initial is not None:
                self.logger.warning(
                    "Initial values cannot be specified for grid search. " "The set initial value has been invalidated."
                )
                break

        return self.generate_parameter()
