"""Persistent graph models."""

from tortoise import fields, models


class Node(models.Model):
    id = fields.IntField(primary_key=True)
    text = fields.TextField()
    value = fields.FloatField(null=True)
    created_at = fields.TextField()
    updated_at = fields.TextField()

    class Meta:
        table = "nodes"


class Edge(models.Model):
    id = fields.IntField(primary_key=True)
    parent = fields.ForeignKeyField(
        "models.Node", related_name="outgoing", on_delete=fields.RESTRICT
    )
    child = fields.ForeignKeyField(
        "models.Node", related_name="incoming", on_delete=fields.RESTRICT, db_index=True
    )
    observation = fields.TextField()
    action = fields.TextField()
    created_at = fields.TextField()
    updated_at = fields.TextField()

    class Meta:
        table = "edges"
        unique_together = (("parent", "child"),)
