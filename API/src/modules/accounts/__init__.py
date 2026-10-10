"""
Capa comercial de Ellysia: planes, cuotas y organizaciones.

Módulo transversal, no una herramienta: por eso no lleva nombre de deidad y
vive junto a ``users``, ``system``, ``shared`` e ``infrastructure``.
"""

from .model import (
    CompanyProfile,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    Plan,
    PlanLimit,
    Subscription,
    UsageCounter,
)
from .managers import CompanyProfileManager, OrganizationManager, PlanManager
from .services import LimitKey, LimitPeriod, QuotaManager
from .exceptions import PlanFeatureDisabledError, QuotaExceededError
from .endpoints import organizations_blp, plans_blp
from .data_export import EXPORT_TABLES
from .services.user_data import purge_accounts_data
from src.modules.users import UserDataRegistry

# Qué hace ``users`` con los datos de este módulo al borrar una cuenta o al
# exportar sus datos: lo declara ``accounts`` y ``users`` solo recorre el registro.
UserDataRegistry.register(
    "accounts",
    purge=purge_accounts_data,
    deletion_models={"subscription": (Subscription,)},
    export_tables=EXPORT_TABLES,
)

__all__ = [
    "Plan",
    "PlanLimit",
    "Subscription",
    "Organization",
    "OrganizationMember",
    "OrganizationInvitation",
    "UsageCounter",
    "PlanManager",
    "OrganizationManager",
    "CompanyProfile",
    "CompanyProfileManager",
    "QuotaManager",
    "LimitKey",
    "LimitPeriod",
    "PlanFeatureDisabledError",
    "QuotaExceededError",
    "plans_blp",
]
