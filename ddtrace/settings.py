import collections
import logging

from copy import deepcopy

from .span import Span
from .pin import Pin
from .utils.merge import deepmerge


log = logging.getLogger(__name__)


class ConfigException(Exception):
    """Configuration exception when an integration that is not available
    is called in the `Config` object.
    """
    pass


class Config(object):
    """Configuration object that exposes an API to set and retrieve
    global settings for each integration. All integrations must use
    this instance to register their defaults, so that they're public
    available and can be updated by users.
    """
    def __init__(self):
        # use a dict as underlying storing mechanism
        self._config = {}

    def __getattr__(self, name):
        if name not in self._config:
            self._config[name] = IntegrationConfig(self)
        return self._config[name]

    def get_from(self, obj):
        """Retrieves the configuration for the given object.
        Any object that has an attached `Pin` must have a configuration
        and if a wrong object is given, an empty `dict` is returned
        for safety reasons.
        """
        pin = Pin.get_from(obj)
        if pin is None:
            log.debug('No configuration found for %s', obj)
            return {}

        return pin._config

    def _add(self, integration, settings, merge=True):
        """Internal API that registers an integration with given default
        settings.

        :param str integration: The integration name (i.e. `requests`)
        :param dict settings: A dictionary that contains integration settings;
            to preserve immutability of these values, the dictionary is copied
            since it contains integration defaults.
        :param bool merge: Whether to merge any existing settings with those provided,
            or if we should overwrite the settings with those provided;
            Note: when merging existing settings take precedence.
        """
        # DEV: Use `getattr()` to call our `__getattr__` helper
        existing = getattr(self, integration)
        settings = deepcopy(settings)

        if merge:
            # DEV: This may appear backwards keeping `existing` as the "source" and `settings` as
            #   the "destination", but we do not want to let `_add(..., merge=True)` overwrite any
            #   existing settings
            #
            # >>> config.requests['split_by_domain'] = True
            # >>> config._add('requests', dict(split_by_domain=False))
            # >>> config.requests['split_by_domain']
            # True
            self._config[integration] = IntegrationConfig(self, deepmerge(existing, settings))
        else:
            self._config[integration] = IntegrationConfig(self, settings)

    def __repr__(self):
        cls = self.__class__
        integrations = ', '.join(self._config.keys())
        return '{}.{}({})'.format(cls.__module__, cls.__name__, integrations)


class IntegrationConfig(dict):
    """
    Integration specific configuration object.

    This is what you will get when you do::

        from ddtrace import config

        # This is an `IntegrationConfig`
        config.flask

        # `IntegrationConfig` supports both item and attribute accessors
        config.flask.service_name = 'my-service-name'
        config.flask['service_name'] = 'my-service-name'
    """
    def __init__(self, global_config, *args, **kwargs):
        """
        :param global_config:
        :type global_config: Config
        :param args:
        :param kwargs:
        """
        super(IntegrationConfig, self).__init__(*args, **kwargs)
        self.global_config = global_config
        self.hooks = Hooks()

    def __deepcopy__(self, memodict=None):
        new = IntegrationConfig(self.global_config, deepcopy(dict(self)))
        new.hooks = deepcopy(self.hooks)
        return new

    def __repr__(self):
        cls = self.__class__
        keys = ', '.join(self.keys())
        return '{}.{}({})'.format(cls.__module__, cls.__name__, keys)


class Hooks(object):
    """
    Hooks configuration object is used for registering and calling hook functions

    Example::

        @config.falcon.hooks.on('request')
        def on_request(span, request, response):
            pass
    """
    __slots__ = ['_hooks']

    def __init__(self):
        self._hooks = collections.defaultdict(set)

    def __deepcopy__(self, memodict=None):
        hooks = Hooks()
        hooks._hooks = deepcopy(self._hooks)
        return hooks

    def register(self, hook, func=None):
        """
        Function used to register a hook for the provided name.

        Example::

            def on_request(span, request, response):
                pass

            config.falcon.hooks.register('request', on_request)


        If no function is provided then a decorator is returned::

            @config.falcon.hooks.register('request')
            def on_request(span, request, response):
                pass

        :param hook: The name of the hook to register the function for
        :type hook: str
        :param func: The function to register, or ``None`` if a decorator should be returned
        :type func: function, None
        :returns: Either a function decorator if ``func is None``, otherwise ``None``
        :rtype: function, None
        """
        # If they didn't provide a function, then return a decorator
        if not func:
            def wrapper(func):
                self.register(hook, func)
                return func
            return wrapper
        self._hooks[hook].add(func)

    # Provide shorthand `on` method for `register`
    # >>> @config.falcon.hooks.on('request')
    #     def on_request(span, request, response):
    #        pass
    on = register

    def deregister(self, func):
        """
        Function to deregister a function from all hooks it was registered under

        Example::

            @config.falcon.hooks.on('request')
            def on_request(span, request, response):
                pass

            config.falcon.hooks.deregister(on_request)


        :param func: Function hook to register
        :type func: function
        """
        for funcs in self._hooks.values():
            if func in funcs:
                funcs.remove(func)

    def _emit(self, hook, span, *args, **kwargs):
        """
        Function used to call registered hook functions.

        :param hook: The hook to call functions for
        :type hook: str
        :param span: The span to call the hook with
        :type span: :class:`ddtrace.span.Span`
        :param *args: Positional arguments to pass to the hook functions
        :type args: list
        :param **kwargs: Keyword arguments to pass to the hook functions
        :type kwargs: dict
        """
        # Return early if no hooks are registered
        if hook not in self._hooks:
            return

        # Return early if we don't have a Span
        if not isinstance(span, Span):
            return

        # Call registered hooks
        for func in self._hooks[hook]:
            try:
                func(span, *args, **kwargs)
            except Exception as e:
                # DEV: Use log.debug instead of log.error until we have a throttled logger
                log.debug('Failed to run hook {} function {}: {}'.format(hook, func, e))

    def __repr__(self):
        """Return string representation of this class instance"""
        cls = self.__class__
        hooks = ','.join(self._hooks.keys())
        return '{}.{}({})'.format(cls.__module__, cls.__name__, hooks)


# Configure our global configuration object
config = Config()
