import { onBeforeUnmount } from 'vue';
import { useRequest } from 'vue-request';
import { useRoute } from 'vue-router';

import { getTicketCount } from '@services/source/ticketFlow';

import { useEventBus } from '@hooks';

const run = () => {
  const isLoading = ref(true);
  const data = ref<ServiceReturnType<typeof getTicketCount>>({
    DONE: 0,
    MY_APPROVE: 0,
    pending: {
      APPROVE: 0,
      FAILED: 0,
      INNER_HELP: 0,
      INNER_TODO: 0,
      RESOURCE_REPLENISH: 0,
      TODO: 0,
    },
    SELF_MANAGE: 0,
    to_help: {
      APPROVE: 0,
      FAILED: 0,
      INNER_HELP: 0,
      INNER_TODO: 0,
      RESOURCE_REPLENISH: 0,
      TODO: 0,
    },
  });

  const { run } = useRequest(getTicketCount, {
    onSuccess(result) {
      data.value = result;
      isLoading.value = false;
    },
  });

  const eventBus = useEventBus();

  eventBus.on('refreshTicketStatus', run);

  onBeforeUnmount(() => {
    eventBus.off('refreshTicketStatus', run);
  });

  return {
    data,
    loading: isLoading,
  };
};

let context: ReturnType<typeof run> | undefined;

export const useTicketCount = () => {
  const route = useRoute();
  if (!context) {
    context = run();
  }
  onBeforeUnmount(() => {
    setTimeout(() => {
      if (route.name !== 'MyTodos') {
        context = undefined;
      }
    });
  });
  return context;
};
