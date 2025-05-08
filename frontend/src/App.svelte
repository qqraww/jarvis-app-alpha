<script>
  import { onMount } from 'svelte';
  import { fade, fly } from 'svelte/transition';
  
  let isListening = false;
  let status = "Готов к работе";
  let lastCommand = null;
  let statusColor = "text-gray-500";
  let pulse = false;
  
  async function toggleListening() {
    const endpoint = isListening ? '/api/stop' : '/api/start';
    const response = await fetch(`http://localhost:5000${endpoint}`);
    const data = await response.json();
    isListening = !isListening;
    pulse = isListening;
  }
  
  async function updateStatus() {
    const response = await fetch('http://localhost:5000/api/status');
    const data = await response.json();
    status = data.current_status;
    lastCommand = data.last_command;
    
    if (status.includes("Распознано")) {
      statusColor = "text-blue-500";
    } else if (status.includes("Выполняю")) {
      statusColor = "text-green-500";
    } else if (status.includes("не распознана")) {
      statusColor = "text-red-500";
    } else {
      statusColor = "text-gray-500";
    }
  }
  
  onMount(() => {
    const interval = setInterval(updateStatus, 100);
    return () => clearInterval(interval);
  });
</script>

<main class="min-h-screen bg-gradient-to-br from-gray-900 to-black text-white p-8">
  <div class="max-w-4xl mx-auto">
    <header class="text-center mb-12">
      <h1 class="text-5xl font-bold mb-4 bg-clip-text text-transparent bg-gradient-to-r from-blue-500 to-purple-500">
        Jarvis
      </h1>
      <p class="text-xl text-gray-400">Ваш голосовой ассистент</p>
    </header>

    <div class="bg-gray-800 rounded-2xl p-8 shadow-2xl">
      <div class="flex flex-col items-center space-y-8">
        <!-- Статус -->
        <div class="text-center">
          <p class="text-2xl font-medium mb-2">Статус</p>
          <p class={`text-xl ${statusColor} transition-colors duration-300`}>
            {status}
          </p>
        </div>

        <!-- Последняя команда -->
        {#if lastCommand}
          <div class="text-center" in:fade>
            <p class="text-2xl font-medium mb-2">Последняя команда</p>
            <p class="text-xl text-purple-400">{lastCommand}</p>
          </div>
        {/if}

        <!-- Кнопка управления -->
        <button
          class="relative w-32 h-32 rounded-full bg-gradient-to-r from-blue-500 to-purple-500 
                 hover:from-blue-600 hover:to-purple-600 transition-all duration-300 
                 shadow-lg hover:shadow-xl focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-opacity-50"
          on:click={toggleListening}
        >
          <div class="absolute inset-0 flex items-center justify-center">
            {#if isListening}
              <div class="w-24 h-24 rounded-full bg-red-500 animate-pulse"></div>
            {:else}
              <div class="w-24 h-24 rounded-full bg-white"></div>
            {/if}
          </div>
        </button>

        <!-- Индикатор активности -->
        {#if isListening}
          <div class="flex space-x-2" in:fade>
            <div class="w-3 h-3 rounded-full bg-blue-500 animate-pulse"></div>
            <div class="w-3 h-3 rounded-full bg-purple-500 animate-pulse" style="animation-delay: 0.2s"></div>
            <div class="w-3 h-3 rounded-full bg-pink-500 animate-pulse" style="animation-delay: 0.4s"></div>
          </div>
        {/if}
      </div>
    </div>
  </div>
</main>

<style>
  :global(body) {
    margin: 0;
    font-family: 'Inter', sans-serif;
  }
</style> 