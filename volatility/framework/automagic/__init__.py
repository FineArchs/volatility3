import logging
import sys

from volatility.framework import class_subclasses, import_files, interfaces
from volatility.framework.automagic import construct_layers, stacker, windows, pdbscan
from volatility.framework.configuration import requirements

vollog = logging.getLogger(__name__)


def available():
    """Determine all the available automagic classes"""
    import_files(sys.modules[__name__])
    return sorted([clazz() for clazz in class_subclasses(interfaces.automagic.AutomagicInterface)],
                  key = lambda x: x.priority)


def run(automagics, context, configurable, config_path = "", progress_callback = None):
    """Runs through the list of `automagics` in order, allowing them to make changes to the context

    :param automagics: A list of :class:`~volatility.framework.interfaces.automagic.AutomagicInterface` objects
    :param context: The context (that inherits from :class:`~volatility.framework.interfaces.context.ContextInterface`) for modification
    :param configurable: An object that inherits from :class:`~volatility.framework.interfaces.configuration.ConfigurableInterface`
    :param config_path: The path within the `context.config` for options required by the `configurable`
    :param progress_callback: A function that takes a percentage (and an optional description) that will be called periodically

    This is where any automagic is allowed to run, and alter the context in order to satisfy/improve all requirements

       This is where any automagic is allowed to run, and alter the context in order to satisfy/improve all requirements
    """
    for automagic in automagics:
        if not isinstance(automagic, interfaces.automagic.AutomagicInterface):
            raise TypeError("Automagics must only contain AutomagicInterface subclasses")

    if (not isinstance(configurable, interfaces.configuration.ConfigurableInterface)
        and not issubclass(configurable, interfaces.configuration.ConfigurableInterface)):
        raise TypeError("Automagic operates on configurables only")

    # TODO: Fix need for top level config element just because we're using a MultiRequirement to group the
    # configurable's config requirements
    configurable_class = configurable
    if isinstance(configurable, interfaces.configuration.ConfigurableInterface):
        configurable_class = configurable.__class__
    requirement = requirements.MultiRequirement(name = configurable_class.__name__.lower())
    for req in configurable.get_requirements():
        requirement.add_requirement(req)

    for automagic in automagics:
        vollog.info("Running automagic: {}".format(automagic.__class__.__name__))
        automagic(context, config_path, requirement, progress_callback)
