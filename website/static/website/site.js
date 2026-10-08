/* Progressive enhancement for Django-rendered HTML. No client-side rendering. */
(() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const wide = matchMedia('(min-width: 901px)');
  const root = document.documentElement;
  const ease = 'cubic-bezier(0.16, 1, 0.3, 1)';
  const clamp = (value) => Math.min(1, Math.max(0, value));
  const mix = (progress, stops, values) => {
    if (progress <= stops[0]) return values[0];
    for (let i = 1; i < stops.length; i++) {
      if (progress <= stops[i]) {
        const t = (progress - stops[i - 1]) / (stops[i] - stops[i - 1]);
        return values[i - 1] + (values[i] - values[i - 1]) * t;
      }
    }
    return values.at(-1);
  };
  const transition = (element, frames, duration = 240) => {
    element.getAnimations().forEach((animation) => animation.cancel());
    return element.animate(frames, { duration, easing: ease });
  };

  const header = document.querySelector('.nav');
  const toggle = document.querySelector('.nav__toggle');
  const mobileMenu = document.querySelector('#mobile-menu');
  let menuOpen = false;
  let menuAnimation;
  function setMenu(open, instant = false) {
    menuOpen = open;
    menuAnimation?.cancel();
    toggle.setAttribute('aria-expanded', String(open));
    toggle.querySelector('.sr-only').textContent = open ? 'Close menu' : 'Open menu';
    header.dataset.instant = String(instant || reduced.matches);
    header.classList.toggle('nav--solid', open || scrollY > 24);
    mobileMenu.inert = !open;
    if (open) mobileMenu.hidden = false;
    if (instant || reduced.matches) {
      mobileMenu.hidden = !open;
      return;
    }
    menuAnimation = transition(mobileMenu, open
      ? [{ opacity: 0, transform: 'translateY(-8px)' }, { opacity: 1, transform: 'translateY(0)' }]
      : [{ opacity: 1 }, { opacity: 0 }], open ? 200 : 120);
    menuAnimation.onfinish = () => { mobileMenu.hidden = !menuOpen; };
  }
  toggle.hidden = false;
  toggle.addEventListener('click', (event) => setMenu(!menuOpen, event.detail === 0));
  header.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => setMenu(false, true)));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && menuOpen) { setMenu(false, true); toggle.focus(); }
  });

  const filters = [...document.querySelectorAll('[data-filter]')];
  const cards = [...document.querySelectorAll('.card')];
  const panel = document.querySelector('#menu-panel');
  document.querySelector('.filters').hidden = false;
  panel.setAttribute('role', 'tabpanel');
  panel.setAttribute('aria-labelledby', 'tab-all');
  panel.removeAttribute('aria-label');
  function chooseMenu(selected, instant) {
    const id = selected.dataset.filter;
    if (selected.getAttribute('aria-selected') === 'true') return;
    cards.forEach((card) => card.getAnimations().forEach((animation) => animation.cancel()));
    const oldPositions = new Map(cards.filter((card) => !card.hidden).map((card) => [card, card.getBoundingClientRect()]));
    filters.forEach((filter) => {
      const active = filter === selected;
      filter.setAttribute('aria-selected', String(active));
      filter.tabIndex = active ? 0 : -1;
      filter.querySelector('.filter__pill').hidden = !active;
    });
    cards.forEach((card) => { card.hidden = id !== 'all' && card.dataset.group !== id; });
    panel.setAttribute('aria-labelledby', selected.id);
    if (instant || reduced.matches) return;
    cards.filter((card) => !card.hidden).forEach((card) => {
      const old = oldPositions.get(card);
      const current = card.getBoundingClientRect();
      transition(card, old
        ? [{ transform: `translate(${old.left - current.left}px, ${old.top - current.top}px)` }, { transform: 'translate(0, 0)' }]
        : [{ opacity: 0, transform: 'scale(.97)' }, { opacity: 1, transform: 'scale(1)' }]);
    });
  }
  filters.forEach((filter, i) => {
    filter.addEventListener('click', (event) => chooseMenu(filter, event.detail === 0));
    filter.addEventListener('keydown', (event) => {
      let next;
      if (event.key === 'ArrowRight') next = (i + 1) % filters.length;
      if (event.key === 'ArrowLeft') next = (i + filters.length - 1) % filters.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = filters.length - 1;
      if (next === undefined) return;
      event.preventDefault();
      chooseMenu(filters[next], true);
      filters[next].focus();
    });
  });
  document.querySelectorAll('.card__photo img').forEach((img) => {
    const fallback = () => img.parentElement.classList.add('is-missing');
    img.addEventListener('error', fallback);
    if (img.complete && !img.naturalWidth) fallback();
  });

  const story = document.querySelector('.story');
  const stage = document.querySelector('.story__stage');
  const scenes = [...document.querySelectorAll('.scene')];
  const cup = document.querySelector('.story__cup');
  const glow = document.querySelector('.story__glow');
  const watermarks = [...document.querySelectorAll('.watermark')];
  const progressBars = [...document.querySelectorAll('.story__progress span')];
  const beanContainer = document.querySelector('.story__beans');
  const reviews = document.querySelector('.reviews');
  const pause = document.querySelector('.reviews__pause');
  const marquees = [...document.querySelectorAll('.marquee')];
  const footer = document.querySelector('.footer');
  const footerMark = document.querySelector('.footer__mark img');
  const stops = [0, .22, .38, .56, .72, 1];
  const sceneKeys = [
    [[0, .26, .38], [1, 1, 0], [0, 0, -60]],
    [[.22, .34, .60, .72], [0, 1, 1, 0], [60, 0, 0, -60]],
    [[.56, .68, 1], [0, 1, 1], [60, 0, 0]],
  ];
  let beans = [];
  function buildBeans() {
    const specs = wide.matches
      ? [['a', 61, 22, 70, .6, 20], ['b-blur4', 33, 58, 104, 1.3, -30], ['a-blur2', 93, 70, 138, 1.6, 60], ['b-blur2', 2, 8, 96, 1.1, 140], ['a', 55, 74, 46, .4, -80]]
      : [['a', 70, 20, 54, .5, 20], ['b-blur2', 4, 17, 74, .9, 140], ['a-blur2', 84, 44, 84, .7, 60], ['b', 14, 42, 38, .4, -40]];
    beanContainer.replaceChildren();
    beans = specs.map(([image, left, top, size, depth, spin], i) => {
      const element = document.createElement('div');
      element.className = 'bean';
      Object.assign(element.style, { left: `${left}%`, top: `${top}%`, width: `${size}px` });
      const img = document.createElement('img');
      img.src = `${beanContainer.dataset.static}images/bean-${image}.webp`;
      img.alt = '';
      img.draggable = false;
      img.style.animationDelay = `${i * -.5}s`;
      element.append(img);
      beanContainer.append(element);
      return { element, depth, spin };
    });
  }

  let currentScene = -1;
  function updateScroll() {
    header.classList.toggle('nav--solid', menuOpen || scrollY > 24);
    if (reduced.matches) return;
    const rect = story.getBoundingClientRect();
    const progress = clamp(-rect.top / Math.max(1, story.offsetHeight - stage.offsetHeight));
    const active = progress < .3 ? 0 : progress < .64 ? 1 : 2;
    scenes.forEach((scene, index) => {
      const [positions, opacity, y] = sceneKeys[index];
      scene.style.opacity = mix(progress, positions, opacity);
      scene.style.transform = `translateY(${mix(progress, positions, y)}px)`;
      if (active !== currentScene) {
        scene.classList.toggle('is-active', index === active);
        scene.inert = index !== active;
        scene.setAttribute('aria-hidden', String(index !== active));
        progressBars[index].classList.toggle('is-active', index === active);
      }
    });
    currentScene = active;
    story.dataset.scene = active;
    const x = mix(progress, stops, wide.matches ? [0, 0, 16, 16, 12, 12] : [0, 0, 22, 22, 0, 0]);
    const y = mix(progress, stops, wide.matches ? [0, 0, 3, 3, 6, 6] : [0, 0, 0, 0, 8, 8]);
    const scale = mix(progress, stops, wide.matches ? [1, 1, .9, .9, 1.22, 1.22] : [1, 1, .9, .9, 1.15, 1.15]);
    cup.style.transform = `translate(${x}%, ${y}%) rotate(${mix(progress, stops, [-5, -5, 9, 9, 0, 0])}deg) scale(${scale})`;
    glow.style.transform = `scale(${mix(progress, [0, .5, 1], [1, 1.12, 1.45])})`;
    watermarks.forEach((mark) => { mark.style.transform = `translate(${-42 - progress * 16}%, -50%)`; });
    beans.forEach(({ element, depth, spin }) => {
      element.style.transform = `translateY(${-260 * depth * progress}px) rotate(${spin + 220 * depth * progress}deg)`;
    });
    const reviewsRect = reviews.getBoundingClientRect();
    const reviewsProgress = clamp((innerHeight - reviewsRect.top) / (innerHeight + reviewsRect.height));
    marquees.forEach((row, index) => { row.style.transform = `translateX(${(6 - 12 * reviewsProgress) * (index ? -1 : 1)}%)`; });
    const footerRect = footer.getBoundingClientRect();
    const footerProgress = clamp((innerHeight - footerRect.top) / footerRect.height);
    footerMark.style.transform = `translateY(${55 * (1 - footerProgress)}%)`;
    footerMark.style.opacity = clamp(footerProgress / .6);
  }
  let frame = null;
  function scheduleScroll() {
    if (frame !== null) return;
    frame = requestAnimationFrame(() => { frame = null; updateScroll(); });
  }
  document.addEventListener('scroll', scheduleScroll, { passive: true });
  window.addEventListener('resize', () => { if (wide.matches) setMenu(false, true); scheduleScroll(); });
  wide.addEventListener('change', () => { buildBeans(); scheduleScroll(); });

  pause.hidden = false;
  pause.addEventListener('click', () => {
    const paused = reviews.classList.toggle('is-paused');
    pause.setAttribute('aria-pressed', String(paused));
    pause.textContent = paused ? 'Play reviews' : 'Pause reviews';
  });
  const visible = new WeakMap();
  const watchVisibility = new IntersectionObserver((entries) => {
    entries.forEach(({ target, isIntersecting }) => {
      visible.set(target, isIntersecting);
      target.classList.toggle('is-offscreen', !isIntersecting || document.hidden);
    });
  });
  [story, reviews].forEach((element) => watchVisibility.observe(element));
  document.addEventListener('visibilitychange', () => {
    [story, reviews].forEach((element) => element.classList.toggle('is-offscreen', document.hidden || !visible.get(element)));
    if (document.hidden) lenis?.stop(); else { lenis?.start(); scheduleScroll(); }
  });

  const reveals = new IntersectionObserver((entries) => {
    entries.forEach(({ target, isIntersecting }) => {
      if (!isIntersecting) return;
      if (!reduced.matches) transition(target, [{ opacity: .2, transform: 'translateY(24px)' }, { opacity: 1, transform: 'translateY(0)' }], 650);
      reveals.unobserve(target);
    });
  }, { rootMargin: '0px 0px -8% 0px' });
  document.querySelectorAll('[data-reveal]').forEach((element) => reveals.observe(element));

  let lenis;
  function applyMotionPreference() {
    root.classList.toggle('is-reduced', reduced.matches);
    lenis?.destroy();
    lenis = undefined;
    currentScene = -1;
    if (reduced.matches) {
      document.getAnimations().forEach((animation) => animation.cancel());
      scenes.forEach((scene) => {
        scene.style.opacity = '1';
        scene.style.transform = 'none';
        scene.classList.add('is-active');
        scene.inert = false;
        scene.removeAttribute('aria-hidden');
      });
      footerMark.style.transform = 'none';
      footerMark.style.opacity = '1';
      marquees.forEach((row) => { row.style.transform = 'none'; });
    } else if (window.Lenis) {
      lenis = new window.Lenis({ autoRaf: true, lerp: .09, anchors: { offset: -84 } });
    }
    scheduleScroll();
  }
  reduced.addEventListener('change', applyMotionPreference);
  root.classList.add('is-enhanced');
  buildBeans();
  applyMotionPreference();
  updateScroll();
  if (!reduced.matches && scrollY < 40 && !location.hash) {
    document.querySelectorAll('.mask__inner').forEach((line, i) => {
      line.animate([{ transform: 'translateY(105%)' }, { transform: 'translateY(0)' }], { duration: 700, delay: i * 60, easing: ease, fill: 'backwards' });
    });
    transition(cup.querySelector('img'), [{ opacity: .2, transform: 'translateY(-35px) rotate(-8deg) scale(.96)' }, { opacity: 1, transform: 'none' }], 800);
  }

  const form = document.querySelector('.news__form');
  form?.addEventListener('submit', () => {
    const button = form.querySelector('button');
    button.disabled = true;
    button.textContent = 'Signing up…';
  });
  window.addEventListener('pageshow', () => {
    if (form) { const button = form.querySelector('button'); button.disabled = false; button.textContent = 'Sign up'; }
    scheduleScroll();
  });
})();
