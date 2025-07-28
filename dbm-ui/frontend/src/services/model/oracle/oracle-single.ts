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

import { uniq } from 'lodash';

import type { ClusterListEntry, ClusterListNode, ClusterListOperation, ClusterListSpec } from '@services/types';

import { Affinity, affinityMap, ClusterTypes } from '@common/const';

import { t } from '@locales/index';

import ClusterBase from '../_clusterBase';

export default class OracleSingleCluster extends ClusterBase {
  // static SQLSERVER_DESTROY = 'SQLSERVER_DESTROY';
  // static SQLSERVER_DISABLE = 'SQLSERVER_DISABLE';
  // static SQLSERVER_ENABLE = 'SQLSERVER_ENABLE';

  static operationIconMap: Record<string, string> = {
    // [OracleSingleCluster.SQLSERVER_DESTROY]: t('删除中'),
    // [OracleSingleCluster.SQLSERVER_DISABLE]: t('禁用中'),
    // [OracleSingleCluster.SQLSERVER_ENABLE]: t('启用中'),
  };

  static operationTextMap: Record<string, string> = {
    // [OracleSingleCluster.SQLSERVER_DESTROY]: t('删除任务执行中'),
    // [OracleSingleCluster.SQLSERVER_DISABLE]: t('禁用任务执行中'),
    // [OracleSingleCluster.SQLSERVER_ENABLE]: t('启用任务执行中'),
  };

  static statusMap: Record<string, string> = {
    running: t('正常'),
    unavailable: t('异常'),
  };

  static themes: Record<string, string> = {
    running: 'success',
  };

  bk_biz_id: number;
  bk_biz_name: string;
  bk_cloud_id: number;
  bk_cloud_name: string;
  cluster_access_port: number;
  cluster_alias: string;
  cluster_entry: ClusterListEntry[];
  cluster_name: string;
  cluster_spec: ClusterListSpec;
  cluster_stats: Record<'used' | 'total' | 'in_use', number>;
  cluster_subzons: string[];
  cluster_time_zone: string;
  cluster_type: ClusterTypes;
  cluster_type_name: string;
  create_at: string;
  creator: string;
  db_module_id: number;
  db_module_name: string;
  disaster_tolerance_level: Affinity;
  id: number;
  major_version: string;
  master_domain: string;
  operations: ClusterListOperation[];
  permission: {
    access_entry_edit: boolean;
    oracle_edit: boolean;
    oracle_view: boolean;
  };
  phase: string;
  phase_name: string;
  primaries: ClusterListNode[];
  region: string;
  slave_domain: string;
  status: string;
  sync_mode: string;
  update_at: string;
  updater: string;

  constructor(payload: OracleSingleCluster) {
    super(payload);
    this.bk_biz_id = payload.bk_biz_id;
    this.bk_biz_name = payload.bk_biz_name;
    this.bk_cloud_id = payload.bk_cloud_id;
    this.bk_cloud_name = payload.bk_cloud_name;
    this.cluster_subzons = payload.cluster_subzons || [];
    this.cluster_access_port = payload.cluster_access_port;
    this.cluster_alias = payload.cluster_alias;
    this.cluster_entry = payload.cluster_entry || [];
    this.cluster_name = payload.cluster_name;
    this.cluster_spec = payload.cluster_spec || {};
    this.cluster_time_zone = payload.cluster_time_zone;
    this.cluster_stats = payload.cluster_stats || {};
    this.cluster_type = payload.cluster_type;
    this.cluster_type_name = payload.cluster_type_name;
    this.create_at = payload.create_at;
    this.creator = payload.creator;
    this.db_module_id = payload.db_module_id;
    this.db_module_name = payload.db_module_name;
    this.disaster_tolerance_level = payload.disaster_tolerance_level;
    this.id = payload.id;
    this.major_version = payload.major_version;
    this.master_domain = payload.master_domain;
    this.operations = payload.operations;
    this.permission = payload.permission || {};
    this.phase = payload.phase;
    this.phase_name = payload.phase_name;
    this.region = payload.region;
    this.slave_domain = payload.slave_domain;
    this.status = payload.status;
    this.primaries = payload.primaries;
    this.sync_mode = payload.sync_mode;
    this.update_at = payload.update_at;
    this.updater = payload.updater;
  }

  get allInstanceList() {
    return [...this.primaries];
  }

  get allIPList() {
    return uniq(this.allInstanceList.map((item) => item.ip));
  }

  // 异常主机IP
  get allUnavailableIPList() {
    return uniq(
      this.allInstanceList.reduce(
        (pre, cur) => [...pre, ...(cur.status === 'unavailable' ? [cur.ip] : [])],
        [] as string[],
      ),
    );
  }

  get dbStatusConfigureObj() {
    const text = OracleSingleCluster.statusMap[this.status] || '--';
    const theme = OracleSingleCluster.themes[this.status] || 'danger';
    return {
      text,
      theme,
    };
  }

  get disasterToleranceLevelName() {
    return affinityMap[this.disaster_tolerance_level];
  }

  get isAbnormal() {
    return this.status === 'abnormal';
  }

  // get isStarting() {
  //   return Boolean(this.operations.find((item) => item.ticket_type === OracleSingleCluster.SQLSERVER_ENABLE));
  // }

  get masterDomainDisplayName() {
    const port = this.primaries[0]?.port;
    const displayName = port ? `${this.master_domain}:${port}` : this.master_domain;
    return displayName;
  }

  get operationDisabled() {
    // 集群异常不支持操作
    if (this.isAbnormal) {
      return true;
    }
    // 被禁用的集群不支持操作
    if (!this.isOnline) {
      return true;
    }
    // 各个操作互斥，有其他任务进行中禁用操作按钮
    if (this.operationTicketId) {
      return true;
    }
    return false;
  }

  // 操作中的状态
  get operationRunningStatus() {
    if (this.operations.length < 1) {
      return '';
    }
    const operation = this.runningOperation;
    if (!operation) {
      return '';
    }
    return operation.ticket_type;
  }

  get operationStatusIcon() {
    return OracleSingleCluster.operationIconMap[this.operationRunningStatus];
  }

  // 操作中的状态描述文本
  get operationStatusText() {
    return OracleSingleCluster.operationTextMap[this.operationRunningStatus];
  }

  get operationTagTips() {
    return this.operations.map((item) => ({
      icon: OracleSingleCluster.operationIconMap[item.ticket_type],
      ticketId: item.ticket_id,
      tip: OracleSingleCluster.operationTextMap[item.ticket_type],
    }));
  }

  // 操作中的单据 ID
  get operationTicketId() {
    if (this.operations.length < 1) {
      return 0;
    }
    const operation = this.runningOperation;
    if (!operation) {
      return 0;
    }
    return operation.ticket_id;
  }

  get roleFailedInstanceInfo() {
    return {
      Master: ClusterBase.getRoleFaildInstanceList(this.primaries),
    };
  }

  get runningOperation() {
    const operateTicketTypes = Object.keys(OracleSingleCluster.operationTextMap);
    return this.operations.find((item) => operateTicketTypes.includes(item.ticket_type) && item.status === 'RUNNING');
  }
}
