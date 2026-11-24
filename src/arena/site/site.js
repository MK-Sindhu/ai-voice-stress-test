// Players for the call timelines, and the filters over the list of failures.
(() => {
  const LEFT = 62, RIGHT = 12, WIDTH = 920;   // must match timeline_svg in report.py
  const fmt = s => Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0');
  let current = null;

  document.querySelectorAll('.call[data-src]').forEach(el => {
    const svg = el.querySelector('svg'), head = el.querySelector('.playhead');
    const button = el.querySelector('.play'), time = el.querySelector('.time');
    const duration = parseFloat(el.dataset.duration);
    let audio = null;

    const draw = () => {
      const x = LEFT + Math.min(audio.currentTime / duration, 1) * (WIDTH - LEFT - RIGHT);
      head.setAttribute('x1', x); head.setAttribute('x2', x); head.style.opacity = 1;
      time.textContent = fmt(audio.currentTime) + ' / ' + fmt(duration);
      if (!audio.paused) requestAnimationFrame(draw);
    };
    const setState = playing => {
      el.classList.toggle('playing', playing);
      button.setAttribute('aria-label', playing ? 'Pause recording' : 'Play recording');
    };
    const load = () => {
      if (audio) return;
      audio = new Audio(el.dataset.src);
      audio.addEventListener('play', () => { setState(true); draw(); });
      audio.addEventListener('pause', () => setState(false));
      audio.addEventListener('ended', () => setState(false));
      el.stop = () => audio.pause();
    };
    const play = () => {
      load();
      if (current && current !== el && current.stop) current.stop();
      current = el;
      audio.play();
    };
    button.addEventListener('click', () => { load(); audio.paused ? play() : audio.pause(); });
    svg.addEventListener('click', event => {
      const box = svg.getBoundingClientRect();
      const x = (event.clientX - box.left) / box.width * WIDTH;
      load();
      audio.currentTime = Math.max(0, Math.min(1, (x - LEFT) / (WIDTH - LEFT - RIGHT))) * duration;
      play();
    });
  });

  // Filters: one agent at a time, optionally one kind of scenario.
  const cards = [...document.querySelectorAll('.card[data-agent]')];
  const chips = [...document.querySelectorAll('.chip[data-filter]')];
  if (!chips.length) return;
  const showing = document.querySelector('.showing');
  const first = name => (chips.find(c => c.dataset.filter === name) || { dataset: {} }).dataset.value;
  const state = { agent: first('agent') || 'all', family: 'all' };
  const apply = () => {
    let shown = 0;
    cards.forEach(card => {
      const on = (state.agent === 'all' || card.dataset.agent === state.agent)
        && (state.family === 'all' || card.dataset.family === state.family);
      card.hidden = !on; shown += on;
    });
    chips.forEach(c => c.setAttribute('aria-pressed', String(state[c.dataset.filter] === c.dataset.value)));
    if (showing) showing.textContent = shown
      ? `Showing ${shown} of ${cards.length} recorded failures`
      : 'No failure of this kind for this agent.';
  };
  chips.forEach(c => c.addEventListener('click', () => { state[c.dataset.filter] = c.dataset.value; apply(); }));
  const openTarget = () => {
    const card = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (!card || !card.dataset.agent) return;
    if (chips.some(c => c.dataset.filter === 'agent')) state.agent = card.dataset.agent;
    state.family = 'all';
    apply();
    card.scrollIntoView();
  };
  window.addEventListener('hashchange', openTarget);
  apply();
  openTarget();
})();
