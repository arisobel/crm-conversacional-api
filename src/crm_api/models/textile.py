"""Atributo têxtil do artigo, em camada separada do catálogo.

O catálogo diz **qual artigo é**; esta camada diz **do que ele é feito**. As duas
não se misturam de propósito: `products` carrega preço publicado atrás de si, e
mexer nele para acomodar atributo obrigaria a migrar dado comercial por causa de
cadastro descritivo (ADR-027).

A composição resolve uma pergunta concreta que o robô recebe toda semana — "tem
poliéster?" — e que hoje não alcança POY, alta tenacidade, Reflex nem recoberto,
que **são** poliéster e não estão marcados como tal em lugar nenhum: a
matéria-prima vive dentro de `commercial_name` e `specification` como texto
livre.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from crm_api.models.base import Base


class Fiber(Base):
    """Fibra têxtil reconhecida pelo tenant.

    Vocabulário fechado e curado, não taxonomia livre: `PES` é poliéster em
    qualquer planilha do setor, e deixar cada um cadastrar a sua faria "PES",
    "POL" e "Poliester" conviverem — exatamente o que o `normalized_name` de
    `ProductGroup` existe para impedir do outro lado. Aqui a curadoria é o seed,
    não uma restrição de forma.
    """

    __tablename__ = "fibers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="ux_fiber_code"),
        Index("ix_fibers_tenant", "tenant_id", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    # Sigla do setor: PES, CV, CO, PUE, PA, EL. É por ela que o CSV casa.
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProductComposition(Base):
    """Percentual de uma fibra em um artigo.

    Multivalorada porque a composição real é: `65PES/35CV`, `92PES 8PUE`,
    `70PES/30CO`. Um campo de texto não responde "tem algo com pelo menos 60% de
    poliéster", que é a consulta que motivou a tabela.

    **Ausência não é negativa.** Artigo sem linha aqui é artigo cujo cadastro
    ainda não foi feito, não artigo sem fibra — e por isso ele nunca é escondido
    de quem perguntou por poliéster. O serviço devolve os dois conjuntos
    separados, e quem decide o que fazer com o segundo é a apresentação.

    A soma de 100% **não** é restrição de banco: ela cruza linhas, e um gatilho
    para isso não se paga num catálogo de centenas de itens. Fica no serviço, que
    é o único caminho de escrita.

    `ON DELETE CASCADE` no artigo, diferente de `product_group_members`: lá o
    vínculo é classificação que alguém montou e vale preservar; aqui a linha é
    uma propriedade do artigo, e sem o artigo ela não descreve nada.
    """

    __tablename__ = "product_compositions"
    __table_args__ = (
        UniqueConstraint("product_id", "fiber_id", name="ux_product_composition"),
        CheckConstraint(
            "percent > 0 AND percent <= 100", name="ck_product_composition_percent"
        ),
        Index("ix_product_compositions_product", "product_id"),
        # Caminho quente: "artigos de poliéster deste tenant".
        Index("ix_product_compositions_fiber", "tenant_id", "fiber_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    fiber_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fibers.id"), index=True)
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
