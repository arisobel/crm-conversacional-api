import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from crm_api.models.base import Base


class ProductFamily(Base):
    __tablename__ = "product_families"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "sku"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_families.id"), index=True)
    sku: Mapped[str] = mapped_column(Text)
    commercial_name: Mapped[str] = mapped_column(Text)
    specification: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str] = mapped_column(String, default="KG")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CustomerPreferredProduct(Base):
    """Seleção, alias e ordem de um produto para um cliente.

    Já existia no DDL desde `0001`; o modelo ORM entra em R1 porque a carteira
    precisa filtrar clientes por produto preferido.
    """

    __tablename__ = "customer_preferred_products"
    __table_args__ = (UniqueConstraint("customer_id", "product_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    customer_alias: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    include_by_default: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ProductGroup(Base):
    """Agrupamento livre de artigos, N↔N, para segmentação e disparo.

    Convive com `ProductFamily` e não a substitui, porque as duas fazem coisas
    diferentes. **Família é layout**: ela agrupa e ordena a tabela de preço que
    o cliente recebe, e por isso precisa ser uma só por artigo — com duas, não
    haveria sob qual cabeçalho imprimir. **Grupo é consulta**: é o "grupo de
    poliéster" do disparo, e ali a multiplicidade é o ponto. Um fio de alta
    tenacidade é poliéster *e* é alta-tenacidade; como família teria que ser um
    ou outro.

    `normalized_name` existe porque a criação é livre e a taxonomia é
    compartilhada. Sem ele, "poliester", "poliéster" e "POLIÉSTER" nascem como
    três grupos e o público de um disparo racha em silêncio — ninguém percebe
    que metade dos clientes ficou de fora. O combobox da tela evita a maior
    parte disso; esta restrição é o que sobrevive a uma chamada de API e a um
    clique apressado.
    """

    __tablename__ = "product_groups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "normalized_name", name="ux_product_group_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    # O nome como foi digitado; é o que aparece na tela.
    name: Mapped[str] = mapped_column(Text)
    # Sem acento e em caixa baixa; é o que a unicidade compara.
    normalized_name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Quem criou. O grupo é do tenant, não de quem o criou — "poliéster" que
    # significasse coisas diferentes por representante tornaria o disparo
    # imprevisível. A autoria fica só para auditoria.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ProductGroupMember(Base):
    """Artigo dentro de um grupo. Sem ordem: grupo não é apresentado, é filtrado."""

    __tablename__ = "product_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "product_id", name="ux_product_group_member"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_groups.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    added_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
