/*
 * TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
 *
 * Copyright (C) 2017-2023 THL A29 Limited, a Tencent company. All rights reserved.
 *
 * Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at https://opensource.org/licenses/MIT
 *
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed
 * on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for
 * the specific language governing permissions and limitations under the License.
 */

import DorisModel from '@services/model/doris/doris';
import DorisDetailModel from '@services/model/doris/doris-detail';
import DorisInstanceModel from '@services/model/doris/doris-instance';
import DorisMachineModel from '@services/model/doris/doris-machine';
import DorisNodeModel from '@services/model/doris/doris-node';
import DorisPasswordModel from '@services/model/doris/doris-password';
import type { ListBase } from '@services/types';

import http from '../http';

const getRootPath = () => `/apis/bigdata/bizs/${window.PROJECT_CONFIG.BIZ_ID}/doris/doris_resources`;

/**
 * 获取集群列表
 */
export function getDorisList(params: {
  creator?: string;
  domain?: string;
  id?: number;
  ip?: string;
  limit?: number;
  name?: string;
  offset?: number;
}) {
  return http.get<ListBase<DorisModel[]>>(`${getRootPath()}/`, params).then((data) => ({
    ...data,
    results: data.results.map(
      (item) =>
        new DorisModel(
          Object.assign(item, {
            permission: Object.assign({}, item.permission, data.permission),
          }),
        ),
    ),
  }));
}

/**
 * 获取查询返回字段
 */
export function getDorisTableFields() {
  return http.get<ListBase<DorisModel[]>>(`${getRootPath()}/get_table_fields/`);
}

/**
 * 获取实例列表
 */
export function getDorisInstanceList(params: {
  cluster_id?: number;
  instance_address?: string;
  ip?: string;
  limit?: number;
  offset?: number;
  port?: string;
  role?: string;
}) {
  return http.get<ListBase<DorisInstanceModel[]>>(`${getRootPath()}/list_instances/`, params).then((data) => ({
    ...data,
    results: data.results.map((item: DorisInstanceModel) => new DorisInstanceModel(item)),
  }));
}

/**
 * 获取实例详情
 */
export function retrieveDorisInstance(params: { bk_biz_id: number }) {
  return http.get<ListBase<DorisModel[]>>(`${getRootPath()}/retrieve_instance/`, params);
}

/**
 * 获取集群详情
 */
export function getDorisDetail(params: { id: number }) {
  return http.get<DorisDetailModel>(`${getRootPath()}/${params.id}/`).then((data) => new DorisDetailModel(data));
}

/**
 * 获取集群节点
 */
export function getDorisNodes(params: { cluster_id: number }) {
  return http.get<ListBase<DorisModel[]>>(`${getRootPath()}/${params.cluster_id}/get_nodes/`);
}

/**
 * 获取集群拓扑
 */
export function getDorisTopoGraph(params: { cluster_id: number }) {
  return http.get<ListBase<DorisModel[]>>(`${getRootPath()}/${params.cluster_id}/get_topo_graph/`);
}

/**
 * 获取 Doris 集群访问密码
 */
export function getDorisPassword(params: { cluster_id: number }) {
  return http
    .get<DorisPasswordModel>(`${getRootPath()}/${params.cluster_id}/get_password/`)
    .then((data) => new DorisPasswordModel(data));
}

/**
 * 获取 Doris 集群节点列表信息
 */
export function getDorisNodeList(params: { bk_biz_id: number; cluster_id: number; no_limit: number }) {
  return http
    .get<ListBase<Array<DorisNodeModel>>>(`${getRootPath()}/${params.cluster_id}/list_nodes/`, params)
    .then((data) => ({
      ...data,
      results: data.results.map(
        (item) =>
          new DorisNodeModel(
            Object.assign(item, {
              permission: data.permission,
            }),
          ),
      ),
    }));
}

/**
 * 导出集群数据为 excel 文件
 */
export function exportDorisClusterToExcel(params: { cluster_ids?: number[] }) {
  return http.post<string>(`${getRootPath()}/export_cluster/`, params, { responseType: 'blob' });
}

/**
 * 导出实例数据为 excel 文件
 */
export function exportDorisInstanceToExcel(params: { bk_host_ids?: number[] }) {
  return http.post<string>(`${getRootPath()}/export_instance/`, params, { responseType: 'blob' });
}

/**
 * 查询主机列表
 */
export function getDorisMachineList(params: {
  add_role_count?: boolean;
  bk_agent_id?: string;
  bk_city_name?: string;
  bk_cloud_id?: number;
  bk_host_id?: number;
  bk_os_name?: string;
  cluster_ids?: string;
  cluster_type?: string;
  creator?: string;
  instance_role?: string;
  ip?: string;
  limit?: number;
  machine_type?: string;
  offset?: number;
}) {
  return http.get<ListBase<DorisMachineModel[]>>(`${getRootPath()}/list_machines/`, params).then((data) => ({
    ...data,
    results: data.results.map((item) => new DorisMachineModel(item)),
  }));
}
