import { useI18n } from 'vue-i18n';

import DbTable from '@components/db-table/index.vue';

import { execCopy, messageWarn } from '@utils';

import type { ClusterModel, ISupportClusterType } from '../types';

export default <T extends ISupportClusterType>(props: {
  getTableInstance: () => InstanceType<typeof DbTable> | undefined;
  selectedList: ClusterModel<T>[];
}) => {
  const { t } = useI18n();

  const handleCopySelected = (field: keyof ClusterModel<T>) => {
    const copyList = props.selectedList.map((item) => item[field as keyof ClusterModel<T>]);

    execCopy(copyList.join('\n'), t('复制成功，共n条', { n: copyList.length }));
  };

  const handleCopyAll = (field: keyof ClusterModel<T>) => {
    props
      .getTableInstance()!
      .getAllData<ClusterModel<T>>()
      .then((data) => {
        if (data.length < 1) {
          messageWarn(t('暂无数据可复制'));
          return;
        }
        const copyList = data.map((item) => item[field as keyof ClusterModel<T>]);
        execCopy(copyList.join('\n'), t('复制成功，共n条', { n: data.length }));
      });
  };

  return {
    handleCopyAll,
    handleCopySelected,
  };
};
