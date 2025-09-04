# -*- coding: utf-8 -*-
"""
TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
Copyright (C) 2017-2023 THL A29 Limited, a Tencent company. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at https://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""
from django.utils.decorators import method_decorator
from django.utils.translation import ugettext as _
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.response import Response

from backend.bk_web.pagination import AuditedLimitOffsetPagination
from backend.bk_web.swagger import common_swagger_auto_schema
from backend.bk_web.viewsets import AuditedModelViewSet
from backend.db_meta.models import Tag
from backend.db_services.tag import serializers
from backend.db_services.tag.filters import TagListFilter
from backend.db_services.tag.handlers import TagHandler
from backend.iam_app.dataclass import ActionEnum, ResourceEnum
from backend.iam_app.handlers.drf_perm.tag import TagPermission
from backend.iam_app.handlers.permission import Permission

SWAGGER_TAG = _("标签")


@method_decorator(
    name="partial_update",
    decorator=common_swagger_auto_schema(
        operation_summary=_("更新标签"), tags=[SWAGGER_TAG], request_body=serializers.UpdateTagSerializer()
    ),
)
@method_decorator(
    name="list",
    decorator=common_swagger_auto_schema(operation_summary=_("查询标签列表"), tags=[SWAGGER_TAG]),
)
class TagViewSet(AuditedModelViewSet):
    """
    标签视图
    """

    queryset = Tag.objects.all()
    serializer_class = serializers.TagSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    pagination_class = AuditedLimitOffsetPagination
    filter_class = TagListFilter
    ordering_fields = ["create_at", "creator", "key"]

    action_permission_map = {("related_resources", "list", "verify_duplicated"): []}
    default_permission_class = [TagPermission()]

    def get_queryset(self):
        return self.filter_by_tenant_id(super().get_queryset())

    @common_swagger_auto_schema(
        operation_summary=_("查询的标签列表"),
        tags=[SWAGGER_TAG],
    )
    @Permission.decorator_external_permission_field(
        actions=[ActionEnum.GLOBAL_RESOURCE_TAG_MANAGE],
    )
    @Permission.decorator_external_permission_field(
        param_field=lambda d: int(d.get("bk_biz_id", 0)),
        actions=[ActionEnum.RESOURCE_TAG_MANAGE],
        resource_meta=ResourceEnum.BUSINESS,
    )
    def list(self, request, *args, **kwargs):
        """
        查询标签列表
        """
        return super().list(request, *args, **kwargs)

    @common_swagger_auto_schema(
        operation_summary=_("查询标签关联资源"), request_body=serializers.QueryRelatedResourceSerializer(), tags=[SWAGGER_TAG]
    )
    @action(methods=["POST"], detail=False, serializer_class=serializers.QueryRelatedResourceSerializer)
    def related_resources(self, request, *args, **kwargs):
        """
        查询标签关联资源
        """
        validated_data = self.params_validate(self.get_serializer_class())
        return Response(TagHandler.query_related_resources(validated_data["ids"], validated_data.get("resource_type")))

    @common_swagger_auto_schema(
        operation_summary=_("批量创建标签"), request_body=serializers.BatchCreateTagsSerializer(), tags=[SWAGGER_TAG]
    )
    @action(methods=["POST"], detail=False, serializer_class=serializers.BatchCreateTagsSerializer)
    def batch_create(self, request, *args, **kwargs):
        """
        创建标签
        """
        validated_data = self.params_validate(self.get_serializer_class())
        return Response(
            TagHandler.batch_create(**validated_data, creator=request.user.username, tenant_id=request.user.tenant_id)
        )

    @common_swagger_auto_schema(
        operation_summary=_("批量删除标签"), request_body=serializers.DeleteTagsSerializer(), tags=[SWAGGER_TAG]
    )
    @action(methods=["DELETE"], detail=False, serializer_class=serializers.DeleteTagsSerializer)
    def batch_delete(self, request, *args, **kwargs):
        """
        删除标签
        """
        validated_data = self.params_validate(self.get_serializer_class())
        return Response(TagHandler.delete_tags(validated_data["bk_biz_id"], validated_data["ids"]))

    @common_swagger_auto_schema(
        operation_summary=_("校验标签是否重复"), request_body=serializers.BatchCreateTagsSerializer(), tags=[SWAGGER_TAG]
    )
    @action(methods=["POST"], detail=False, serializer_class=serializers.BatchCreateTagsSerializer)
    def verify_duplicated(self, request, *args, **kwargs):
        """
        校验
        """
        validated_data = self.params_validate(self.get_serializer_class())
        return Response(
            TagHandler.verify_duplicated(validated_data["type"], validated_data["bk_biz_id"], validated_data["tags"])
        )
