import type { DetailBase, DetailClusters } from '../common';

export interface ClusterRollbackDataCopy extends DetailBase {
  clusters: DetailClusters;
  //  dts 复制类型: 回档临时实例数据回写
  dts_copy_type: 'copy_from_rollback_instance';
  infos: {
    dst_cluster: number;
    key_black_regex: string; // 排除key
    key_white_regex: string; // 包含key
    recovery_time_point: string; // 构造到指定时间
    src_cluster: string; // 构造产物访问入口
  }[];
  write_mode: string;
}
