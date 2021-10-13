from typing import TYPE_CHECKING, Type, cast

import ormar
from ormar import ForeignKey, ManyToMany
from ormar.fields import Through
from ormar.models.descriptors import RelationDescriptor
from ormar.models.helpers.sqlalchemy import adjust_through_many_to_many_model
from ormar.relations import AliasManager

if TYPE_CHECKING:  # pragma no cover
    from ormar import Model
    from ormar.fields import ManyToManyField, ForeignKeyField

alias_manager = AliasManager()


def register_relation_on_build(field: "ForeignKeyField") -> None:
    """
    Registers ForeignKey relation in alias_manager to set a table_prefix.
    Registration include also reverse relation side to be able to join both sides.

    Relation is registered by model name and relation field name to allow for multiple
    relations between two Models that needs to have different
    aliases for proper sql joins.

    :param field: relation field
    :type field: ForeignKey class
    """
    alias_manager.add_relation_type(
        source_model=field.owner,
        relation_name=field.name,
        reverse_name=field.get_source_related_name(),
    )


def register_many_to_many_relation_on_build(field: "ManyToManyField") -> None:
    """
    Registers connection between through model and both sides of the m2m relation.
    Registration include also reverse relation side to be able to join both sides.

    Relation is registered by model name and relation field name to allow for multiple
    relations between two Models that needs to have different
    aliases for proper sql joins.

    By default relation name is a model.name.lower().

    :param field: relation field
    :type field: ManyToManyField class
    """
    alias_manager.add_relation_type(
        source_model=field.through,
        relation_name=field.default_source_field_name(),
        reverse_name=field.get_source_related_name(),
    )
    alias_manager.add_relation_type(
        source_model=field.through,
        relation_name=field.default_target_field_name(),
        reverse_name=field.get_related_name(),
    )


def expand_reverse_relationship(model_field: "ForeignKeyField") -> None:
    """
    If the reverse relation has not been set before it's set here.

    :param model_field:
    :type model_field:
    :return: None
    :rtype: None
    """
    if reverse_field_not_already_registered(model_field=model_field):
        register_reverse_model_fields(model_field=model_field)


def expand_reverse_relationships(model: Type["Model"]) -> None:
    """
    Iterates through model_fields of given model and verifies if all reverse
    relation have been populated on related models.

    If the reverse relation has not been set before it's set here.

    :param model: model on which relation should be checked and registered
    :type model: Model class
    """
    model_fields = list(model.Meta.model_fields.values())
    for model_field in model_fields:
        if model_field.is_relation and not model_field.has_unresolved_forward_refs():
            model_field = cast("ForeignKeyField", model_field)
            expand_reverse_relationship(model_field=model_field)


def register_reverse_model_fields(model_field: "ForeignKeyField") -> None:
    """
    Registers reverse ForeignKey field on related model.
    By default it's name.lower()+'s' of the model on which relation is defined.

    But if the related_model name is provided it's registered with that name.
    Autogenerated reverse fields also set related_name to the original field name.

    :param model_field: original relation ForeignKey field
    :type model_field: relation Field
    """
    related_name = model_field.get_related_name()
    # TODO: Reverse relations does not register pydantic fields?
    if model_field.is_multi:
        model_field.to.Meta.model_fields[related_name] = ManyToMany(  # type: ignore
            model_field.owner,
            through=model_field.through,
            name=related_name,
            virtual=True,
            related_name=model_field.name,
            owner=model_field.to,
            self_reference=model_field.self_reference,
            self_reference_primary=model_field.self_reference_primary,
            orders_by=model_field.related_orders_by,
            skip_field=model_field.skip_reverse,
            through_relation_name=model_field.through_reverse_relation_name,
            through_reverse_relation_name=model_field.through_relation_name,
        )
        # register foreign keys on through model
        model_field = cast("ManyToManyField", model_field)
        register_through_shortcut_fields(model_field=model_field)
        adjust_through_many_to_many_model(model_field=model_field)
    else:
        model_field.to.Meta.model_fields[related_name] = ForeignKey(  # type: ignore
            model_field.owner,
            real_name=related_name,
            virtual=True,
            related_name=model_field.name,
            owner=model_field.to,
            self_reference=model_field.self_reference,
            orders_by=model_field.related_orders_by,
            skip_field=model_field.skip_reverse,
        )
    if not model_field.skip_reverse:
        setattr(model_field.to, related_name, RelationDescriptor(name=related_name))


def register_through_shortcut_fields(model_field: "ManyToManyField") -> None:
    """
    Registers m2m relation through shortcut on both ends of the relation.

    :param model_field: relation field defined in parent model
    :type model_field: ManyToManyField
    """
    through_model = model_field.through
    through_name = through_model.get_name(lower=True)
    related_name = model_field.get_related_name()

    model_field.owner.Meta.model_fields[through_name] = Through(
        through_model,
        real_name=through_name,
        virtual=True,
        related_name=model_field.name,
        owner=model_field.owner,
        nullable=True,
    )

    model_field.to.Meta.model_fields[through_name] = Through(
        through_model,
        real_name=through_name,
        virtual=True,
        related_name=related_name,
        owner=model_field.to,
        nullable=True,
    )
    setattr(model_field.owner, through_name, RelationDescriptor(name=through_name))
    setattr(model_field.to, through_name, RelationDescriptor(name=through_name))


def register_relation_in_alias_manager(field: "ForeignKeyField") -> None:
    """
    Registers the relation (and reverse relation) in alias manager.
    The m2m relations require registration of through model between
    actual end models of the relation.

    Delegates the actual registration to:
    m2m - register_many_to_many_relation_on_build
    fk - register_relation_on_build

    :param field: relation field
    :type field: ForeignKey or ManyToManyField class
    """
    if field.is_multi:
        if field.has_unresolved_forward_refs():
            return
        field = cast("ManyToManyField", field)
        register_many_to_many_relation_on_build(field=field)
    elif field.is_relation and not field.is_through:
        if field.has_unresolved_forward_refs():
            return
        register_relation_on_build(field=field)


def verify_related_name_dont_duplicate(
    related_name: str, model_field: "ForeignKeyField"
) -> None:
    """
    Verifies whether the used related_name (regardless of the fact if user defined or
    auto generated) is already used on related model, but is connected with other model
    than the one that we connect right now.

    :raises ModelDefinitionError: if name is already used but lead to different related
    model
    :param related_name:
    :type related_name:
    :param model_field: original relation ForeignKey field
    :type model_field: relation Field
    :return: None
    :rtype: None
    """
    fk_field = model_field.to.Meta.model_fields.get(related_name)
    if not fk_field:  # pragma: no cover
        return
    if fk_field.to != model_field.owner and fk_field.to.Meta != model_field.owner.Meta:
        raise ormar.ModelDefinitionError(
            f"Relation with related_name "
            f"'{related_name}' "
            f"leading to model "
            f"{model_field.to.get_name(lower=False)} "
            f"cannot be used on model "
            f"{model_field.owner.get_name(lower=False)} "
            f"because it's already used by model "
            f"{fk_field.to.get_name(lower=False)}"
        )


def reverse_field_not_already_registered(model_field: "ForeignKeyField") -> bool:
    """
    Checks if child is already registered in parents pydantic fields.

    :raises ModelDefinitionError: if related name is already used but lead to different
    related model
    :param model_field: original relation ForeignKey field
    :type model_field: relation Field
    :return: result of the check
    :rtype: bool
    """
    related_name = model_field.get_related_name()
    check_result = related_name not in model_field.to.Meta.model_fields
    check_result2 = model_field.owner.get_name() not in model_field.to.Meta.model_fields

    if not check_result:
        verify_related_name_dont_duplicate(
            related_name=related_name, model_field=model_field
        )
    if not check_result2:
        verify_related_name_dont_duplicate(
            related_name=model_field.owner.get_name(), model_field=model_field
        )

    return check_result and check_result2
