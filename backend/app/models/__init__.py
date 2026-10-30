# Импорт всех моделей в одном месте: так они гарантированно регистрируются
# в Base.metadata (нужно Alembic для autogenerate и для резолва relationship).
from app.models.category import FoodCategory
from app.models.letter import Letter
from app.models.order import EDITABLE_STATUSES, Order, OrderItem, OrderStatus
from app.models.supplier import Supplier, SupplierOffer
from app.models.user import EmailVerificationCode, User

__all__ = [
    "EDITABLE_STATUSES",
    "EmailVerificationCode",
    "FoodCategory",
    "Letter",
    "Order",
    "OrderItem",
    "OrderStatus",
    "Supplier",
    "SupplierOffer",
    "User",
]
