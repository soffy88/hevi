"""
Service Registry for managing microservices
"""
from typing import Dict, Type, Any, Optional
from .user_service import user_service
from .task_service import task_service
from .cache_service import cache_service
from .response_service import api_response_service
from .auth_service import auth_microservice
from .rate_limit_service import rate_limit_service
from .async_task_service import async_task_service


class ServiceRegistry:
    """
    Central registry for all microservices in the application
    """
    
    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._service_classes: Dict[str, Type] = {}
    
    def register_service(self, name: str, service_instance: Any, service_class: Type = None):
        """
        Register a service instance with an optional class reference
        """
        self._services[name] = service_instance
        if service_class:
            self._service_classes[name] = service_class
    
    def get_service(self, name: str) -> Optional[Any]:
        """
        Retrieve a service instance by name
        """
        return self._services.get(name)
    
    def get_service_class(self, name: str) -> Optional[Type]:
        """
        Retrieve a service class by name
        """
        return self._service_classes.get(name)
    
    def initialize_default_services(self):
        """
        Initialize all default services
        """
        # Register default services
        self.register_service('user_service', user_service)
        self.register_service('task_service', task_service)
        self.register_service('cache_service', cache_service)
        self.register_service('api_response_service', api_response_service)
        self.register_service('auth_service', auth_microservice)
        self.register_service('rate_limit_service', rate_limit_service)
        self.register_service('async_task_service', async_task_service)
    
    def get_all_service_names(self) -> list[str]:
        """
        Get all registered service names
        """
        return list(self._services.keys())


# Global service registry instance
service_registry = ServiceRegistry()
service_registry.initialize_default_services()


def get_service(service_name: str) -> Optional[Any]:
    """
    Convenience function to get a service from the registry
    """
    return service_registry.get_service(service_name)