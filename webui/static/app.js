const state = {
  libraries: {},
  entries: [],
  fields: [],
  fontDirectory: '/config/fonts',
  filter: '',
  pendingEntryId: null,
  collapsedEntries: new Set(),
  lastSavedEntries: new Map(),
  previewCache: {},
  cardTypeExtras: {},
};

const dom = {
  entries: document.getElementById('entries'),
  search: document.getElementById('series-search'),
  toggleSearch: document.getElementById('toggle-search'),
  closeSearch: document.getElementById('close-search'),
  header: document.querySelector('.app-header'),
  addEntry: document.getElementById('add-entry'),
  save: document.getElementById('save-config'),
  expandAll: document.getElementById('expand-all-entries'),
  collapseAll: document.getElementById('collapse-all-entries'),
  downloadSources: document.getElementById('download-sources'),
  runBuilder: document.getElementById('run-builder'),
  modals: document.getElementById('modals'),
};

const toastContainer = document.createElement('div');
toastContainer.className = 'toast-container';
document.body.appendChild(toastContainer);

const CLIENT_LOG_ENDPOINT = '/api/client-log';
const PREVIEW_CACHE_STORAGE_KEY = 'tcm-preview-cache';

const EPISODE_TEXT_FORMAT_GROUPS = [
  {
    label: 'Season',
    options: [
      { label: 'Season Number', value: '{season_number}', example: '3' },
      { label: 'Cardinal Season Number', value: '{season_number_cardinal}', example: 'three' },
      { label: 'Ordinal Season Number', value: '{season_number_ordinal}', example: 'third' },
    ],
  },
  {
    label: 'Episode',
    options: [
      { label: 'Episode Number', value: '{episode_number}', example: '10' },
      { label: 'Cardinal Episode Number', value: '{episode_number_cardinal}', example: 'ten' },
      { label: 'Ordinal Episode Number', value: '{episode_number_ordinal}', example: 'tenth' },
    ],
  },
  {
    label: 'Absolute Numbering',
    options: [
      { label: 'Absolute Episode Number', value: '{abs_number}', example: '47' },
      {
        label: 'Cardinal Absolute Episode Number',
        value: '{absolute_number_cardinal}',
        example: 'forty-seven',
      },
      {
        label: 'Ordinal Absolute Episode Number',
        value: '{absolute_number_ordinal}',
        example: 'forty-seventh',
      },
    ],
  },
];

const cardTypePreviewElement = document.createElement('div');
cardTypePreviewElement.className = 'card-type-preview';
cardTypePreviewElement.style.left = '0px';
cardTypePreviewElement.style.top = '0px';
const cardTypePreviewImage = document.createElement('img');
cardTypePreviewImage.alt = 'Card type preview';
cardTypePreviewElement.appendChild(cardTypePreviewImage);
document.body.appendChild(cardTypePreviewElement);

const entryPreviewHoverElement = document.createElement('div');
entryPreviewHoverElement.className = 'entry-preview-hover';
entryPreviewHoverElement.style.left = '0px';
entryPreviewHoverElement.style.top = '0px';
const entryPreviewHoverImage = document.createElement('img');
entryPreviewHoverImage.alt = 'Entry preview';
entryPreviewHoverElement.appendChild(entryPreviewHoverImage);
document.body.appendChild(entryPreviewHoverElement);

const episodeTextHelperElement = createEpisodeTextFormatHelper();
document.body.appendChild(episodeTextHelperElement);

let cardTypePreviewVisible = false;
const hoverMediaQuery =
  typeof window.matchMedia === 'function'
    ? window.matchMedia('(hover: hover)')
    : null;

let entryPreviewHoverVisible = false;
let activeEpisodeTextInput = null;

function canShowCardTypePreview() {
  if (!hoverMediaQuery) {
    return true;
  }
  return hoverMediaQuery.matches;
}

function positionCardTypePreview(event) {
  if (!event) {
    return;
  }
  const offset = 18;
  const estimatedWidth =
    cardTypePreviewElement.offsetWidth ||
    cardTypePreviewImage.naturalWidth ||
    320;
  const estimatedHeight =
    cardTypePreviewElement.offsetHeight ||
    cardTypePreviewImage.naturalHeight ||
    180;
  let left = event.clientX + offset;
  let top = event.clientY + offset;
  const maxLeft = window.innerWidth - estimatedWidth - 12;
  const maxTop = window.innerHeight - estimatedHeight - 12;
  if (left > maxLeft) {
    left = Math.max(12, event.clientX - estimatedWidth - offset);
  }
  if (top > maxTop) {
    top = Math.max(12, event.clientY - estimatedHeight - offset);
  }
  cardTypePreviewElement.style.left = `${Math.max(12, left)}px`;
  cardTypePreviewElement.style.top = `${Math.max(12, top)}px`;
}

function showCardTypePreview(src, label, event) {
  if (!src || !canShowCardTypePreview()) {
    return;
  }
  cardTypePreviewImage.src = src;
  cardTypePreviewImage.alt = label ? `${label} preview` : 'Card type preview';
  positionCardTypePreview(event);
  cardTypePreviewElement.classList.add('visible');
  cardTypePreviewVisible = true;
}

function moveCardTypePreview(event) {
  if (!cardTypePreviewVisible) {
    return;
  }
  positionCardTypePreview(event);
}

function hideCardTypePreview() {
  cardTypePreviewVisible = false;
  cardTypePreviewElement.classList.remove('visible');
}

function enableCardTypePreview(wrapper) {
  if (!wrapper) {
    return;
  }
  if (wrapper.dataset.previewHandlers === 'true') {
    return;
  }
  wrapper.dataset.previewHandlers = 'true';
  wrapper.addEventListener('mouseenter', (event) => {
    const src = wrapper.dataset.previewSrc;
    if (!src) {
      return;
    }
    showCardTypePreview(src, wrapper.dataset.previewLabel, event);
  });
  wrapper.addEventListener('mousemove', moveCardTypePreview);
  wrapper.addEventListener('mouseleave', hideCardTypePreview);
}

function canShowEntryPreviewHover() {
  if (!hoverMediaQuery) {
    return true;
  }
  return hoverMediaQuery.matches;
}

function positionEntryPreviewHover(event) {
  if (!event) {
    return;
  }
  const offset = 18;
  const estimatedWidth =
    entryPreviewHoverElement.offsetWidth ||
    entryPreviewHoverImage.naturalWidth ||
    640;
  const estimatedHeight =
    entryPreviewHoverElement.offsetHeight ||
    entryPreviewHoverImage.naturalHeight ||
    360;
  let left = event.clientX + offset;
  let top = event.clientY + offset;
  const maxLeft = window.innerWidth - estimatedWidth - 12;
  const maxTop = window.innerHeight - estimatedHeight - 12;
  if (left > maxLeft) {
    left = Math.max(12, event.clientX - estimatedWidth - offset);
  }
  if (top > maxTop) {
    top = Math.max(12, event.clientY - estimatedHeight - offset);
  }
  entryPreviewHoverElement.style.left = `${Math.max(12, left)}px`;
  entryPreviewHoverElement.style.top = `${Math.max(12, top)}px`;
}

function showEntryPreviewHover(src, label, event) {
  if (!src || !canShowEntryPreviewHover()) {
    return;
  }
  entryPreviewHoverImage.src = src;
  entryPreviewHoverImage.alt = label ? `${label} preview` : 'Entry preview';
  positionEntryPreviewHover(event);
  entryPreviewHoverElement.classList.add('visible');
  entryPreviewHoverVisible = true;
}

function moveEntryPreviewHover(event) {
  if (!entryPreviewHoverVisible) {
    return;
  }
  positionEntryPreviewHover(event);
}

function hideEntryPreviewHover() {
  entryPreviewHoverVisible = false;
  entryPreviewHoverElement.classList.remove('visible');
}

function enableEntryPreviewHover(wrapper, entry) {
  if (!wrapper || wrapper.dataset.previewHoverHandlers === 'true') {
    return;
  }
  wrapper.dataset.previewHoverHandlers = 'true';
  wrapper.addEventListener('mouseenter', (event) => {
    const src = entry?.previewSrc || wrapper.dataset.previewSrc;
    showEntryPreviewHover(src, entry?.name, event);
  });
  wrapper.addEventListener('mousemove', moveEntryPreviewHover);
  wrapper.addEventListener('mouseleave', hideEntryPreviewHover);
}

// -----------------------------------------------------------------------------
// Episode text helper
// -----------------------------------------------------------------------------
function createEpisodeTextFormatHelper() {
  const helper = document.createElement('div');
  helper.className = 'episode-text-helper';
  helper.setAttribute('role', 'dialog');
  helper.setAttribute('aria-label', 'Episode text format helper');

  const header = document.createElement('div');
  header.className = 'episode-text-helper__header';
  const title = document.createElement('strong');
  title.textContent = 'Episode text helper';
  const hint = document.createElement('span');
  hint.textContent = 'Click a placeholder to insert it where your cursor is.';
  header.append(title, hint);
  helper.appendChild(header);

  const groupsContainer = document.createElement('div');
  groupsContainer.className = 'episode-text-helper__groups';

  EPISODE_TEXT_FORMAT_GROUPS.forEach((group) => {
    const groupElement = document.createElement('div');
    groupElement.className = 'episode-text-helper__group';

    const groupTitle = document.createElement('div');
    groupTitle.className = 'episode-text-helper__group-title';
    groupTitle.textContent = group.label;
    groupElement.appendChild(groupTitle);

    const optionsList = document.createElement('div');
    optionsList.className = 'episode-text-helper__options';

    group.options.forEach((option) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'episode-text-helper__option';
      button.textContent = option.example
        ? `${option.label} (${option.example})`
        : option.label;
      button.addEventListener('click', () => insertEpisodeTextFormatValue(option.value));
      optionsList.appendChild(button);
    });

    groupElement.appendChild(optionsList);
    groupsContainer.appendChild(groupElement);
  });

  helper.appendChild(groupsContainer);
  return helper;
}

function enableEpisodeTextFormatHelper(input) {
  if (!input || input.dataset.episodeTextHelper === 'true') {
    return;
  }
  input.dataset.episodeTextHelper = 'true';
  input.addEventListener('focus', () => showEpisodeTextFormatHelper(input));
  input.addEventListener('keyup', () => positionEpisodeTextFormatHelper());
}

function showEpisodeTextFormatHelper(input) {
  activeEpisodeTextInput = input;
  episodeTextHelperElement.classList.add('visible');
  positionEpisodeTextFormatHelper();
}

function hideEpisodeTextFormatHelper() {
  activeEpisodeTextInput = null;
  episodeTextHelperElement.classList.remove('visible');
}

function positionEpisodeTextFormatHelper() {
  if (!activeEpisodeTextInput || !episodeTextHelperElement.classList.contains('visible')) {
    return;
  }
  const rect = activeEpisodeTextInput.getBoundingClientRect();
  const viewportPadding = 12;
  const helperWidth = episodeTextHelperElement.offsetWidth || 0;
  const helperHeight = episodeTextHelperElement.offsetHeight || 0;
  let left = window.scrollX + rect.left;
  let top = window.scrollY + rect.bottom + 8;
  const maxLeft = window.scrollX + window.innerWidth - helperWidth - viewportPadding;
  if (left > maxLeft) {
    left = Math.max(window.scrollX + viewportPadding, maxLeft);
  }
  if (top + helperHeight > window.scrollY + window.innerHeight - viewportPadding) {
    top = window.scrollY + rect.top - helperHeight - 8;
  }
  if (top < window.scrollY + viewportPadding) {
    top = window.scrollY + rect.bottom + 8;
  }
  episodeTextHelperElement.style.left = `${Math.max(window.scrollX + viewportPadding, left)}px`;
  episodeTextHelperElement.style.top = `${Math.max(window.scrollY + viewportPadding, top)}px`;
}

function insertEpisodeTextFormatValue(value) {
  if (!activeEpisodeTextInput) {
    return;
  }
  const input = activeEpisodeTextInput;
  const start = typeof input.selectionStart === 'number' ? input.selectionStart : input.value.length;
  const end = typeof input.selectionEnd === 'number' ? input.selectionEnd : start;
  const newValue = `${input.value.slice(0, start)}${value}${input.value.slice(end)}`;
  input.value = newValue;
  const cursorPosition = start + value.length;
  input.setSelectionRange(cursorPosition, cursorPosition);
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.focus();
  positionEpisodeTextFormatHelper();
}

function episodeTextHelperContains(target) {
  return (
    target === activeEpisodeTextInput ||
    (activeEpisodeTextInput && activeEpisodeTextInput.contains(target)) ||
    episodeTextHelperElement.contains(target)
  );
}

document.addEventListener('mousedown', (event) => {
  if (!episodeTextHelperElement.classList.contains('visible')) {
    return;
  }
  if (episodeTextHelperContains(event.target)) {
    return;
  }
  hideEpisodeTextFormatHelper();
});

document.addEventListener('focusin', (event) => {
  if (!episodeTextHelperElement.classList.contains('visible')) {
    return;
  }
  if (episodeTextHelperContains(event.target)) {
    return;
  }
  hideEpisodeTextFormatHelper();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && episodeTextHelperElement.classList.contains('visible')) {
    hideEpisodeTextFormatHelper();
  }
});

window.addEventListener('scroll', () => positionEpisodeTextFormatHelper(), true);
window.addEventListener('resize', () => positionEpisodeTextFormatHelper(), true);

function logToServer(level, message, context = {}) {
  try {
    fetch(CLIENT_LOG_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level, message, context }),
      keepalive: true,
    }).catch(() => {});
  } catch (error) {
    // Logging errors should never affect UX.
  }
}

// -----------------------------------------------------------------------------
// Initialization
// -----------------------------------------------------------------------------
async function init() {
  try {
    loadPreviewCache();
    await loadMetadata();
    await loadConfiguration();
    registerEvents();
    setSearchVisibility(false);
    renderEntries();
    requestEntryPreviews();
  } catch (error) {
    showToast(`Failed to load configuration: ${error.message}`, 'error');
  }
}

document.addEventListener('DOMContentLoaded', init);

async function loadMetadata() {
  const response = await fetch('/api/meta');
  if (!response.ok) {
    throw new Error('Unable to load metadata');
  }
  const data = await response.json();
  state.fields = data.fields || [];
  state.fontDirectory = data.fontDirectory || state.fontDirectory;
  state.cardTypeExtras = data.cardTypeExtras || {};
}

async function loadConfiguration() {
  const response = await fetch('/api/config');
  if (!response.ok) {
    throw new Error('Unable to load tv.yml');
  }
  const data = await response.json();
  state.libraries = data.libraries || {};
  state.entries = (data.series || []).map((entry, index) => ({
    id: `${entry.name}-${index}`,
    name: entry.name,
    config: entry.config || {},
  }));
  sortEntries();
  state.collapsedEntries = new Set(state.entries.map((entry) => entry.id));
  syncSavedEntrySnapshots();
  state.entries.forEach(restoreCachedPreview);
}

function setSearchVisibility(isVisible) {
  if (!dom.header) {
    return;
  }
  dom.header.classList.toggle('search-active', isVisible);
  if (dom.toggleSearch) {
    dom.toggleSearch.setAttribute('aria-expanded', String(isVisible));
  }
}

function registerEvents() {
  if (dom.search) {
    dom.search.addEventListener('input', (event) => {
      state.filter = event.target.value.toLowerCase();
      renderEntries();
    });

    dom.search.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        setSearchVisibility(false);
      }
    });
  }

  if (dom.toggleSearch && dom.header) {
    dom.toggleSearch.addEventListener('click', () => {
      const isActive = !dom.header.classList.contains('search-active');
      setSearchVisibility(isActive);
      if (isActive && dom.search) {
        dom.search.focus();
      }
    });
  }

  if (dom.closeSearch) {
    dom.closeSearch.addEventListener('click', () => setSearchVisibility(false));
  }

  dom.addEntry.addEventListener('click', () => openAddEntryModal());

  dom.save.addEventListener('click', () => saveConfiguration());

  if (dom.expandAll) {
    dom.expandAll.addEventListener('click', () => setAllEntriesCollapsed(false));
  }

  if (dom.collapseAll) {
    dom.collapseAll.addEventListener('click', () => setAllEntriesCollapsed(true));
  }

  if (dom.downloadSources) {
    dom.downloadSources.addEventListener('click', () =>
      triggerServerAction(
        dom.downloadSources,
        '/api/actions/download-sources',
        'Downloaded logos and sources',
        { workingLabel: 'Downloading...' }
      )
    );
  }

  if (dom.runBuilder) {
    dom.runBuilder.addEventListener('click', () =>
      triggerServerAction(
        dom.runBuilder,
        '/api/actions/build',
        'Builder run complete',
        {
          workingLabel: 'Building...',
          refresh: true,
          onSuccess: () => refreshEntryPreviews(),
        }
      )
    );
  }
}

// -----------------------------------------------------------------------------
// Rendering
// -----------------------------------------------------------------------------
function renderEntries() {
  dom.entries.innerHTML = '';

  const filtered = state.entries.filter((entry) =>
    entry.name.toLowerCase().includes(state.filter)
  );

  if (filtered.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-entries';
    empty.innerHTML =
      '<p>No series match the search. Use "Add entry" to create one.</p>';
    dom.entries.appendChild(empty);
    return;
  }

  let highlightElement = null;

  filtered.forEach((entry) => {
    const element = renderEntry(entry);
    if (entry.id === state.pendingEntryId) {
      highlightElement = element;
    }
    dom.entries.appendChild(element);
  });

  if (highlightElement) {
    requestAnimationFrame(() => {
      highlightElement.classList.add('entry-highlight');
      highlightElement.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
      setTimeout(() => {
        highlightElement.classList.remove('entry-highlight');
      }, 2000);
      state.pendingEntryId = null;
    });
  }

  requestEntryPreviews(filtered);
}

function classifyLogoTone(image) {
  if (!image || !image.complete || image.naturalWidth === 0 || image.naturalHeight === 0) {
    return null;
  }

  const maxDimension = 96;
  const scale = Math.min(1, maxDimension / Math.max(image.naturalWidth, image.naturalHeight));
  const width = Math.max(1, Math.round(image.naturalWidth * scale));
  const height = Math.max(1, Math.round(image.naturalHeight * scale));

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;

  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) {
    return null;
  }

  context.drawImage(image, 0, 0, width, height);
  const { data } = context.getImageData(0, 0, width, height);

  let totalLuminance = 0;
  let countedPixels = 0;

  for (let index = 0; index < data.length; index += 4) {
    const alpha = data[index + 3];
    if (alpha < 16) {
      continue;
    }

    const luminance = 0.2126 * data[index] + 0.7152 * data[index + 1] + 0.0722 * data[index + 2];
    totalLuminance += luminance;
    countedPixels += 1;
  }

  if (countedPixels === 0) {
    return null;
  }

  const averageLuminance = totalLuminance / countedPixels;
  return averageLuminance >= 150 ? 'light' : 'dark';
}

function applyLogoStroke(logoElement) {
  const tone = classifyLogoTone(logoElement);
  logoElement.classList.remove('entry-logo--light', 'entry-logo--dark');

  if (!tone) {
    return;
  }

  const logoToneClass = tone === 'light' ? 'entry-logo--light' : 'entry-logo--dark';
  logoElement.classList.add(logoToneClass);
}

function renderEntry(entry) {
  const container = document.createElement('article');
  container.className = 'entry';
  container.dataset.entryId = entry.id;

  const header = document.createElement('div');
  header.className = 'entry-header';

  const summary = document.createElement('div');
  summary.className = 'entry-summary';

  const toggleButton = document.createElement('button');
  toggleButton.type = 'button';
  toggleButton.className = 'entry-toggle';

  const syncToggleAppearance = () => {
    const collapsed = isEntryCollapsed(entry.id);
    toggleButton.textContent = collapsed ? '+' : '−';
    toggleButton.setAttribute('aria-expanded', String(!collapsed));
    toggleButton.setAttribute('aria-label', collapsed ? 'Expand entry' : 'Collapse entry');
    container.classList.toggle('entry--collapsed', collapsed);
  };

  toggleButton.addEventListener('click', () => {
    const nextState = !isEntryCollapsed(entry.id);
    setEntryCollapsed(entry.id, nextState);
    syncToggleAppearance();
  });

  const logo = document.createElement('img');
  logo.className = 'entry-logo';
  logo.alt = `${entry.name} logo`;
  logo.loading = 'lazy';
  logo.src = `/api/series-logo?name=${encodeURIComponent(entry.name)}`;
  logo.addEventListener('load', () => applyLogoStroke(logo));
  logo.addEventListener('error', () => {
    logo.classList.add('entry-logo--missing');
    logo.classList.remove('entry-logo--light', 'entry-logo--dark');
    logo.removeAttribute('src');
  });

  const preview = document.createElement('div');
  preview.className = 'entry-preview';
  preview.dataset.entryId = entry.id;

  const previewImage = document.createElement('img');
  previewImage.className = 'entry-preview__image';
  previewImage.alt = `${entry.name} preview`;

  const previewPlaceholder = document.createElement('span');
  previewPlaceholder.className = 'entry-preview__placeholder';
  previewPlaceholder.textContent = 'Generating preview...';

  if (entry.previewSrc) {
    previewImage.src = entry.previewSrc;
    preview.classList.add('entry-preview--loaded');
    preview.dataset.previewSrc = entry.previewSrc;
  } else if (entry.previewError) {
    previewPlaceholder.textContent = entry.previewError;
    preview.classList.add('entry-preview--error');
  }

  preview.append(previewImage, previewPlaceholder);

  enableEntryPreviewHover(preview, entry);

  const media = document.createElement('div');
  media.className = 'entry-media';
  media.append(logo, preview);

  const titleInput = document.createElement('input');
  titleInput.type = 'text';
  titleInput.value = entry.name;
  titleInput.addEventListener('input', (event) => {
    entry.name = event.target.value;
  });
  titleInput.addEventListener('blur', () => {
    sortEntries();
    state.pendingEntryId = entry.id;
    renderEntries();
  });

  const titleContainer = document.createElement('div');
  titleContainer.className = 'entry-title';
  titleContainer.appendChild(titleInput);

  summary.append(toggleButton, media, titleContainer);
  syncToggleAppearance();

  const actions = document.createElement('div');
  actions.className = 'entry-actions';

  const entryPayload = () => ({ name: entry.name, config: entry.config });

  const buildButton = document.createElement('button');
  buildButton.textContent = 'Build cards';
  buildButton.addEventListener('click', () =>
    triggerServerAction(
      buildButton,
      '/api/actions/build-series',
      `Built cards for ${entry.name}`,
      {
        workingLabel: 'Building...',
        refresh: false,
        payload: entryPayload(),
        onSuccess: () => refreshEntryPreviews([entry]),
      }
    )
  );

  const revertButton = document.createElement('button');
  revertButton.textContent = 'Revert cards';
  revertButton.addEventListener('click', () =>
    triggerServerAction(
      revertButton,
      '/api/actions/revert-series',
      `Reverted cards for ${entry.name}`,
      { workingLabel: 'Reverting...', refresh: false, payload: entryPayload() }
    )
  );

  const forgetButton = document.createElement('button');
  forgetButton.textContent = 'Forget cards';
  forgetButton.addEventListener('click', () =>
    triggerServerAction(
      forgetButton,
      '/api/actions/forget-cards',
      `Forgot loaded cards for ${entry.name}`,
      { workingLabel: 'Forgetting...', refresh: false, payload: entryPayload() }
    )
  );

  const previewButton = document.createElement('button');
  previewButton.textContent = 'Preview';
  previewButton.addEventListener('click', () => openPreview(entry));

  const deleteButton = document.createElement('button');
  deleteButton.textContent = 'Remove';
  deleteButton.style.background = 'rgba(227, 107, 107, 0.15)';
  deleteButton.addEventListener('click', () => removeEntry(entry));

  actions.append(
    buildButton,
    revertButton,
    forgetButton,
    previewButton,
    deleteButton
  );
  header.append(summary, actions);

  const body = document.createElement('div');
  body.className = 'entry-body';

  const usedFields = new Set();
  state.fields.forEach((field) => {
    const value = getValue(entry.config, field.path);
    if (value !== undefined) {
      usedFields.add(field.id);
      body.appendChild(renderFieldRow(entry, field, value));
    }
  });

  const addLineButton = document.createElement('button');
  addLineButton.className = 'add-line';
  addLineButton.textContent = '+ Add line';
  addLineButton.addEventListener('click', () => openFieldSelector(entry));
  body.appendChild(addLineButton);

  container.append(header, body);
  return container;
}

function updateEntryPreview(entry) {
  const wrapper = dom.entries.querySelector(
    `[data-entry-id="${entry.id}"] .entry-preview`
  );
  if (!wrapper) {
    return;
  }

  const image = wrapper.querySelector('.entry-preview__image');
  const placeholder = wrapper.querySelector('.entry-preview__placeholder');

  wrapper.classList.remove('entry-preview--error', 'entry-preview--loaded');
  wrapper.dataset.previewSrc = entry.previewSrc || '';

  if (entry.previewSrc && image) {
    image.src = entry.previewSrc;
    image.alt = `${entry.name} preview`;
    wrapper.classList.add('entry-preview--loaded');
    wrapper.dataset.previewSrc = entry.previewSrc;
    if (placeholder) {
      placeholder.textContent = '';
    }
    return;
  }

  if (image) {
    image.removeAttribute('src');
  }

  if (!entry.previewError && placeholder) {
    placeholder.textContent = 'Generating preview...';
  }

  if (entry.previewError && placeholder) {
    placeholder.textContent = entry.previewError;
    wrapper.classList.add('entry-preview--error');
  }
}

function invalidateEntryPreview(entry) {
  entry.previewSrc = null;
  entry.previewError = null;
  entry.previewLoading = false;
  clearPreviewCacheEntry(entry);
  updateEntryPreview(entry);
}

async function loadEntryPreview(entry) {
  if (!entry || entry.previewSrc || entry.previewLoading) {
    return;
  }

  entry.previewLoading = true;
  const requestId = (entry.previewRequestId || 0) + 1;
  entry.previewRequestId = requestId;
  entry.previewError = null;

  try {
    const response = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: entry.name, config: entry.config }),
    });

    if (!response.ok) {
      const message = await response.text();
      throw new Error(message || 'Preview request failed');
    }

    const data = await response.json();
    if (!data?.mime || !data?.data) {
      throw new Error('Preview payload was missing image data');
    }

    if (entry.previewRequestId === requestId) {
      entry.previewSrc = `data:${data.mime};base64,${data.data}`;
      updatePreviewCache(entry);
    }
  } catch (error) {
    if (entry.previewRequestId === requestId) {
      entry.previewError = error.message || 'Preview unavailable';
      clientLog('preview-generation-failed', {
        event: 'preview-generation-failed',
        name: entry.name,
        error: entry.previewError,
      });
    }
  } finally {
    if (entry.previewRequestId === requestId) {
      entry.previewLoading = false;
      updateEntryPreview(entry);
    }
  }
}

function requestEntryPreviews(entries = state.entries) {
  entries.forEach((entry) => {
    void loadEntryPreview(entry);
  });
}

function refreshEntryPreviews(entries = state.entries) {
  entries.forEach((entry) => invalidateEntryPreview(entry));
  requestEntryPreviews(entries);
}

function isEntryCollapsed(entryId) {
  return state.collapsedEntries.has(entryId);
}

function setEntryCollapsed(entryId, collapsed) {
  if (!entryId) {
    return;
  }
  if (collapsed) {
    state.collapsedEntries.add(entryId);
  } else {
    state.collapsedEntries.delete(entryId);
  }
}

function setAllEntriesCollapsed(collapsed) {
  if (collapsed) {
    state.collapsedEntries = new Set(state.entries.map((entry) => entry.id));
  } else {
    state.collapsedEntries = new Set();
  }
  renderEntries();
}

function renderFieldRow(entry, field, value) {
  const row = document.createElement('div');
  row.className = 'field-row';

  const label = document.createElement('label');
  label.textContent = field.label;

  const controls = document.createElement('div');
  controls.className = 'field-controls';

  const removeButton = document.createElement('button');
  removeButton.textContent = 'Remove';
  removeButton.addEventListener('click', () => {
    removeField(entry, field);
  });

  switch (field.type) {
    case 'text':
      controls.appendChild(textInput(entry, field, value));
      break;
    case 'color':
      controls.appendChild(colorInput(entry, field, value));
      break;
    case 'number':
      controls.appendChild(numberInput(entry, field, value));
      break;
    case 'boolean':
      controls.appendChild(booleanSelect(entry, field, value));
      break;
    case 'library':
    case 'style':
    case 'choice':
    case 'font-case':
      controls.appendChild(optionSelect(entry, field, value));
      break;
    case 'card-type':
      controls.appendChild(cardTypePicker(entry, field, value));
      break;
    case 'csv':
      controls.appendChild(csvInput(entry, field, value));
      break;
    case 'translation-list':
      controls.appendChild(translationEditor(entry, field, value));
      break;
    case 'font':
      controls.appendChild(fontPicker(entry, field, value));
      break;
    case 'replacement-map':
      controls.appendChild(replacementEditor(entry, field, value));
      break;
    case 'extras':
      controls.appendChild(extrasEditor(entry, field, value));
      break;
    case 'season-map':
      controls.appendChild(seasonEditor(entry, field, value));
      break;
    case 'range-map':
      controls.appendChild(mapEditor(entry, field, value, 'Name', 'Range'));
      break;
    case 'hide-seasons':
      controls.appendChild(hideSeasonsSelect(entry, field, value));
      break;
    default:
      controls.appendChild(textInput(entry, field, value));
      break;
  }

  controls.appendChild(removeButton);
  row.append(label, controls);
  return row;
}

// -----------------------------------------------------------------------------
// Field renderers
// -----------------------------------------------------------------------------
function textInput(entry, field, value) {
  const input = document.createElement('input');
  input.type = 'text';
  input.value = value ?? '';
  input.addEventListener('input', (event) => {
    updateField(entry, field, event.target.value || undefined);
  });
  if (field.id === 'episode_text_format') {
    enableEpisodeTextFormatHelper(input);
  }
  return input;
}

function isValidHexColor(value) {
  if (!value) {
    return false;
  }
  return /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(value.trim());
}

function isColorFieldKey(key) {
  if (!key) {
    return false;
  }
  const normalised = key.toString().toLowerCase();
  return normalised.includes('color') || normalised.includes('colour');
}

function colorInput(entry, field, value) {
  const wrapper = document.createElement('div');
  wrapper.className = 'inline-actions color-input';

  const color = document.createElement('input');
  color.type = 'color';
  color.value = isValidHexColor(value) ? value : '#ffffff';

  const text = document.createElement('input');
  text.type = 'text';
  text.placeholder = '#RRGGBB';
  text.value = value ?? '';

  const setValue = (newValue) => {
    updateField(entry, field, newValue || undefined);
  };

  color.addEventListener('input', (event) => {
    const selected = event.target.value;
    text.value = selected;
    setValue(selected);
  });

  text.addEventListener('input', (event) => {
    const rawValue = event.target.value.trim();
    setValue(rawValue);
    if (isValidHexColor(rawValue)) {
      color.value = rawValue;
    }
  });

  wrapper.append(color, text);
  return wrapper;
}

function defaultValueForField(field) {
  if (field.default !== undefined) {
    return field.default;
  }
  switch (field.type) {
    case 'boolean':
      return false;
    case 'translation-list':
      return [];
    case 'replacement-map':
    case 'extras':
    case 'season-map':
    case 'range-map':
      return {};
    default:
      return '';
  }
}

function numberInput(entry, field, value) {
  const input = document.createElement('input');
  input.type = 'number';
  input.value = value ?? '';
  input.addEventListener('input', (event) => {
    const raw = event.target.value.trim();
    const numeric = raw === '' ? undefined : Number(raw);
    updateField(entry, field, numeric);
  });
  return input;
}

function booleanSelect(entry, field, value) {
  const select = document.createElement('select');
  ['true', 'false'].forEach((option) => {
    const opt = document.createElement('option');
    opt.value = option;
    opt.textContent = option;
    if (String(value) === option) {
      opt.selected = true;
    }
    select.appendChild(opt);
  });
  select.addEventListener('change', (event) => {
    updateField(entry, field, event.target.value === 'true');
  });
  return select;
}

function optionSelect(entry, field, value) {
  const select = document.createElement('select');
  const choices = [...(field.choices || [])].sort((a, b) =>
    (a.label || a.value || '').localeCompare(b.label || b.value || '', undefined, {
      sensitivity: 'base',
    })
  );
  const hasValue =
    value !== undefined && choices.some((choice) => choice.value === value);

  if (!hasValue && value !== undefined && value !== '') {
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = value;
    opt.selected = true;
    select.appendChild(opt);
  }

  choices.forEach((choice) => {
    const opt = document.createElement('option');
    opt.value = choice.value;
    opt.textContent = choice.label || choice.value;
    if (choice.value === value) {
      opt.selected = true;
    }
    select.appendChild(opt);
  });
  select.addEventListener('change', (event) => {
    updateField(entry, field, event.target.value);
  });
  return select;
}

function cardTypePicker(entry, field, value) {
  const container = document.createElement('div');
  container.className = 'card-type-control';

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'card-type-trigger';

  const current = document.createElement('span');
  current.className = 'card-type-current';
  const caret = document.createElement('span');
  caret.className = 'card-type-caret';
  caret.innerHTML = '&#x25BE;';

  button.append(current, caret);
  container.appendChild(button);

  const updateLabel = (val) => {
    if (!val) {
      current.textContent = 'Select card type';
      return;
    }
    const match = (field.choices || []).find(
      (choice) => choice.value === val
    );
    if (match) {
      current.textContent = match.label || match.value;
    } else {
      current.textContent = `Custom: ${val}`;
    }
  };

  updateLabel(value);

  button.addEventListener('click', () => {
    console.debug('Card type picker opened', {
      entry: entry.name,
      field: field.name,
      currentValue: value,
    });
    logToServer('DEBUG', 'Card type picker opened', {
      entry: entry.name,
      field: field.name,
      currentValue: value,
    });
    openCardTypeModal(field, value, (selection) => {
      value = selection;
      updateField(entry, field, selection);
      updateLabel(selection);
    });
  });

  return container;
}

function slugifyCardType(value) {
  return (value || '')
    .toString()
    .trim()
    .toLowerCase()
    .replace(/([a-z])([0-9])/g, '$1-$2')
    .replace(/([0-9])([a-z])/g, '$1-$2')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function cardTypeImageCandidates(choice) {
  const slug = choice.slug || slugifyCardType(choice.value || choice.label || '');
  const explicit = [];
  if (choice.thumbnail) {
    if (Array.isArray(choice.thumbnail)) {
      explicit.push(...choice.thumbnail);
    } else {
      explicit.push(choice.thumbnail);
    }
  }

  if (explicit.length > 0) {
    return [...new Set(explicit.filter(Boolean))];
  }

  if (!slug) {
    return [];
  }

  return [`/api/card-types/thumbnail?slug=${encodeURIComponent(slug)}`];
}

function cardTypePreviewSource(choice) {
  const slug = choice.slug || slugifyCardType(choice.value || choice.label || '');
  if (!slug) {
    return undefined;
  }
  return `/api/card-types/preview?slug=${encodeURIComponent(slug)}`;
}

function createCardTypeThumbnail(choice) {
  const wrapper = document.createElement('div');
  wrapper.className = 'card-type-thumbnail';
  wrapper.dataset.previewLabel = choice.label || choice.value || 'Card type';

  const fallback = document.createElement('span');
  fallback.className = 'card-type-thumbnail-fallback';
  fallback.textContent = choice.label || choice.value || 'Card type';
  wrapper.appendChild(fallback);

  const candidates = cardTypeImageCandidates(choice);
  const previewSrc = cardTypePreviewSource(choice);
  console.debug('Card type thumbnail candidates', {
    choice: choice.value,
    candidates,
  });
  if (candidates.length === 0) {
    wrapper.classList.add('card-type-thumbnail-empty');
    logToServer('INFO', 'No thumbnail candidates available', {
      choice: choice.value,
    });
    return wrapper;
  }

  const img = document.createElement('img');
  img.alt = `${choice.label || choice.value} example`;
  img.decoding = 'async';
  img.style.opacity = '0';
  img.style.transition = 'opacity 150ms ease-out';

  let index = 0;
  const tryNext = () => {
    if (index >= candidates.length) {
      console.debug('All thumbnail candidates failed', {
        choice: choice.value,
        candidates,
      });
      logToServer('INFO', 'All thumbnail candidates failed', {
        choice: choice.value,
        candidates,
      });
      wrapper.classList.add('card-type-thumbnail-empty');
      return;
    }
    const candidate = candidates[index++];
    console.debug('Attempting card type thumbnail', {
      choice: choice.value,
      candidate,
      position: index,
      total: candidates.length,
    });
    img.src = candidate;
  };

  img.addEventListener('load', () => {
    console.debug('Card type thumbnail loaded', {
      choice: choice.value,
      src: img.currentSrc || img.src,
    });
    img.style.opacity = '1';
    wrapper.classList.add('card-type-thumbnail-loaded');
    wrapper.prepend(img);
    fallback.remove();
    wrapper.dataset.previewSrc = previewSrc || img.currentSrc || img.src;
  });

  img.addEventListener('error', (event) => {
    logToServer('INFO', 'Card type thumbnail failed to load', {
      choice: choice.value,
      candidate: img.currentSrc || img.src,
      message: event?.message,
    });
    tryNext();
  });
  wrapper.prepend(img);
  tryNext();

  enableCardTypePreview(wrapper);

  return wrapper;
}

function openCardTypeModal(field, currentValue, onSelect) {
  const modal = buildModal('Select card type');
  addFloatingCloseButton(modal, 'Close card type selector');

  const wrapper = document.createElement('div');
  wrapper.className = 'card-type-modal';

  const search = document.createElement('input');
  search.type = 'search';
  search.placeholder = 'Search card types...';
  search.className = 'modal-search';

  const results = document.createElement('div');
  results.className = 'search-results card-type-results';

  wrapper.append(search, results);
  modal.content.appendChild(wrapper);

  const choices = [...(field.choices || [])].sort((a, b) =>
    (a.label || a.value || '').localeCompare(b.label || b.value || '', undefined, {
      sensitivity: 'base',
    })
  );
  console.debug('Rendering card type modal', {
    choicesCount: choices.length,
    currentValue,
  });

  const renderResults = () => {
    const term = search.value.trim().toLowerCase();
    results.innerHTML = '';
    hideCardTypePreview();

    const matches = choices.filter((choice) => {
      const label = (choice.label || '').toLowerCase();
      const value = (choice.value || '').toLowerCase();
      if (!term) return true;
      return label.includes(term) || value.includes(term);
    });

    console.debug('Card type search results', {
      searchTerm: term,
      matchCount: matches.length,
    });

    if (matches.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'helper-text';
      empty.textContent = 'No card types match your search.';
      results.appendChild(empty);
      return;
    }

    matches.forEach((choice) => {
      const option = document.createElement('button');
      option.type = 'button';
      option.className = 'card-type-option';
      option.setAttribute('aria-pressed', choice.value === currentValue ? 'true' : 'false');
      if (choice.value === currentValue) {
        option.classList.add('selected');
      }

      const thumbnail = createCardTypeThumbnail(choice);

      const title = document.createElement('span');
      title.className = 'card-type-option-title';
      title.textContent = choice.label || choice.value || 'Card type';

      const identifier = document.createElement('span');
      identifier.className = 'card-type-option-value helper-text';
      identifier.textContent = choice.value;

      option.append(thumbnail, title, identifier);

      option.addEventListener('click', () => {
        onSelect(choice.value);
        closeModal(modal.element);
      });

      results.appendChild(option);
    });
  };

  search.addEventListener('input', renderResults);
  renderResults();

  const customWrapper = document.createElement('div');
  customWrapper.className = 'card-type-custom';

  const customLabel = document.createElement('p');
  customLabel.className = 'helper-text';
  customLabel.textContent =
    'Need something else? Provide a custom card type identifier.';

  const customInput = document.createElement('input');
  customInput.type = 'text';
  customInput.placeholder = 'Custom card type identifier';

  const hasCurrent = choices.some((choice) => choice.value === currentValue);
  if (currentValue && !hasCurrent) {
    customInput.value = currentValue;
  }

  const customButton = document.createElement('button');
  customButton.textContent = 'Use custom value';
  customButton.disabled = customInput.value.trim() === '';

  customInput.addEventListener('input', () => {
    customButton.disabled = customInput.value.trim() === '';
  });

  customButton.addEventListener('click', () => {
    const customValue = customInput.value.trim();
    if (!customValue) {
      return;
    }
    onSelect(customValue);
    closeModal(modal.element);
  });

  customWrapper.append(customLabel, customInput, customButton);
  modal.content.appendChild(customWrapper);

}

function csvInput(entry, field, value) {
  const input = document.createElement('input');
  input.type = 'text';
  input.value = Array.isArray(value) ? value.join(', ') : value ?? '';
  input.placeholder = 'comma separated';
  input.addEventListener('input', (event) => {
    updateField(entry, field, event.target.value);
  });
  return input;
}

function normalizeHideSeasonsValue(value) {
  if (value === 'auto') {
    return 'auto';
  }
  if (typeof value === 'string') {
    const normalized = value.toLowerCase();
    if (normalized === 'auto' || normalized === 'false') {
      return normalized;
    }
    if (normalized === 'true') {
      return 'true';
    }
  }
  if (value === false) {
    return 'false';
  }
  return 'true';
}

function hideSeasonsSelect(entry, field, value) {
  const select = document.createElement('select');
  const normalizedValue = normalizeHideSeasonsValue(value);

  ['true', 'false', 'auto'].forEach((option) => {
    const opt = document.createElement('option');
    opt.value = option;
    opt.textContent = option;
    if (normalizedValue === option) {
      opt.selected = true;
    }
    select.appendChild(opt);
  });

  const persistSelection = (selected) => {
    if (selected === 'true') {
      updateField(entry, field, true);
    } else if (selected === 'false') {
      updateField(entry, field, false);
    } else {
      updateField(entry, field, 'auto');
    }
  };

  if (value === undefined) {
    persistSelection(normalizedValue);
  }

  select.addEventListener('change', (event) => {
    persistSelection(event.target.value);
  });

  return select;
}

function translationEditor(entry, field, value) {
  const container = document.createElement('div');
  container.className = 'multi-row sub-card-list';

  const translations = Array.isArray(value)
    ? value.map((item) => ({ ...item }))
    : [];

  const updateTranslations = () => {
    const sanitized = translations
      .map((item) => ({
        language: (item.language || '').trim(),
        key: (item.key || '').trim(),
      }))
      .filter((item) => item.language && item.key);
    updateField(entry, field, sanitized.length > 0 ? sanitized : []);
  };

  const renderRows = () => {
    container.innerHTML = '';
    translations.forEach((translation, index) => {
      const row = document.createElement('div');
      row.className = 'multi-row-item item-card';

      const language = document.createElement('input');
      language.type = 'text';
      language.placeholder = 'Language code';
      language.value = translation.language || '';
      language.addEventListener('input', (event) => {
        translation.language = event.target.value;
        updateTranslations();
      });

      const key = document.createElement('input');
      key.type = 'text';
      key.placeholder = 'Key';
      key.value = translation.key || '';
      key.addEventListener('input', (event) => {
        translation.key = event.target.value;
        updateTranslations();
      });

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'item-remove';
      remove.textContent = '×';
      remove.setAttribute('aria-label', 'Remove translation');
      remove.addEventListener('click', () => {
        translations.splice(index, 1);
        updateTranslations();
        renderRows();
      });

      row.append(language, key, remove);
      container.appendChild(row);
    });

    const add = document.createElement('button');
    add.textContent = '+ Add translation';
    add.addEventListener('click', () => {
      translations.push({ language: '', key: '' });
      updateTranslations();
      renderRows();
    });
    container.appendChild(add);
  };

  renderRows();
  return container;
}

function fontPicker(entry, field, value) {
  const wrapper = document.createElement('div');
  wrapper.className = 'inline-actions';

  const input = document.createElement('input');
  input.type = 'text';
  input.value = value ?? '';
  input.addEventListener('input', (event) => {
    updateField(entry, field, event.target.value || undefined);
  });

  const uploadInput = document.createElement('input');
  uploadInput.type = 'file';
  uploadInput.accept = '.ttf,.otf,.woff,.woff2';
  uploadInput.style.display = 'none';

  const browse = document.createElement('button');
  browse.textContent = 'Browse';
  browse.addEventListener('click', () => openFontBrowser(entry, field, input));

  const upload = document.createElement('button');
  upload.textContent = 'Upload';
  upload.addEventListener('click', () => uploadInput.click());

  uploadInput.addEventListener('change', async (event) => {
    const [file] = event.target.files || [];
    if (!file) return;

    const targetDirectory = PathParent(input.value) || state.fontDirectory;

    upload.disabled = true;
    const originalLabel = upload.textContent;
    upload.textContent = 'Uploading...';

    try {
      const { path } = await uploadFont(file, targetDirectory);
      if (path) {
        input.value = path;
        updateField(entry, field, path);
        showToast(`Uploaded ${file.name}`, 'success');
      }
    } catch (error) {
      const message = error?.message || 'Upload failed';
      showToast(message, 'error');
    } finally {
      upload.disabled = false;
      upload.textContent = originalLabel;
      uploadInput.value = '';
    }
  });

  wrapper.append(input, browse, uploadInput, upload);
  return wrapper;
}

function replacementEditor(entry, field, value) {
  const container = document.createElement('div');
  container.className = 'table-list';

  const replacements = { ...(value || {}) };
  const deleteMissing = Boolean(replacements.delete_missing ?? true);
  const rows = Object.entries(replacements)
    .filter(([key]) => key !== 'delete_missing')
    .map(([key, val]) => ({ find: key, replace: val }));

  const deleteToggle = document.createElement('label');
  deleteToggle.className = 'inline-actions';
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.checked = deleteMissing;
  checkbox.addEventListener('change', () => {
    replacements.delete_missing = checkbox.checked;
    updateReplacements();
  });
  deleteToggle.append(checkbox, document.createTextNode('Delete missing keys'));

  const list = document.createElement('div');
  list.className = 'table-list';

  const updateReplacements = () => {
    const map = {};
    rows
      .filter((row) => row.find !== '')
      .forEach((row) => {
        map[row.find] = row.replace ?? '';
      });
    map.delete_missing = checkbox.checked;
    updateField(entry, field, map);
  };

  const renderRows = () => {
    list.innerHTML = '';
    rows.forEach((row, index) => {
      const line = document.createElement('div');
      line.className = 'table-list-row item-card';

      const find = document.createElement('input');
      find.type = 'text';
      find.placeholder = 'Find';
      find.value = row.find;
      find.addEventListener('input', (event) => {
        row.find = event.target.value;
        updateReplacements();
      });

      const replace = document.createElement('input');
      replace.type = 'text';
      replace.placeholder = 'Replace';
      replace.value = row.replace ?? '';
      replace.addEventListener('input', (event) => {
        row.replace = event.target.value;
        updateReplacements();
      });

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'item-remove';
      remove.textContent = '×';
      remove.setAttribute('aria-label', 'Remove replacement');
      remove.addEventListener('click', () => {
        rows.splice(index, 1);
        updateReplacements();
        renderRows();
      });

      line.append(find, replace, remove);
      list.appendChild(line);
    });

    const add = document.createElement('button');
    add.textContent = '+ Add replacement';
    add.addEventListener('click', () => {
      rows.push({ find: '', replace: '' });
      renderRows();
    });
    list.appendChild(add);
  };

  renderRows();
  container.append(deleteToggle, list);
  return container;
}

function mapEditor(entry, field, value, keyLabel, valueLabel, onUpdate, options = {}) {
  const container = document.createElement('div');
  container.className = 'table-list sub-card-list';

  const rows = Object.entries(value || {}).map(([key, val]) => ({
    key,
    value: val,
  }));

  const list = document.createElement('div');
  list.className = 'table-list';

  const update = () => {
    const map = {};
    rows
      .filter((row) => row.key !== '')
      .forEach((row) => {
        map[row.key] = row.value ?? '';
      });
    if (onUpdate) {
      onUpdate(map);
    }
    updateField(entry, field, map);
  };

  const renderRows = () => {
    list.innerHTML = '';
    rows.forEach((row, index) => {
      const line = document.createElement('div');
      line.className = 'table-list-row item-card';

      const keyInput = document.createElement('input');
      keyInput.type = 'text';
      keyInput.placeholder = keyLabel;
      keyInput.value = row.key;
      keyInput.addEventListener('input', (event) => {
        const wasColorField = isColorFieldKey(row.key);
        row.key = event.target.value;
        update();
        const isNowColorField = isColorFieldKey(row.key);
        if (wasColorField !== isNowColorField) {
          renderRows();
        }
      });

      const renderColorValue = isColorFieldKey(row.key);
      let valueInput;
      if (renderColorValue) {
        const wrapper = document.createElement('div');
        wrapper.className = 'inline-actions color-input';

        const color = document.createElement('input');
        color.type = 'color';
        color.value = isValidHexColor(row.value) ? row.value : '#ffffff';

        const text = document.createElement('input');
        text.type = 'text';
        text.placeholder = '#RRGGBB';
        text.value = row.value ?? '';

        const setValue = (newValue) => {
          row.value = newValue;
          update();
        };

        color.addEventListener('input', (event) => {
          const selected = event.target.value;
          text.value = selected;
          setValue(selected);
        });

        text.addEventListener('input', (event) => {
          const rawValue = event.target.value.trim();
          setValue(rawValue);
          if (isValidHexColor(rawValue)) {
            color.value = rawValue;
          }
        });

        wrapper.append(color, text);
        valueInput = wrapper;
      } else {
        valueInput = document.createElement('input');
        valueInput.type = 'text';
        valueInput.placeholder = valueLabel;
        valueInput.value = row.value ?? '';
        valueInput.addEventListener('input', (event) => {
          row.value = event.target.value;
          update();
        });
      }

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'item-remove';
      remove.textContent = '×';
      remove.setAttribute('aria-label', `Remove ${keyLabel.toLowerCase()}`);
      remove.addEventListener('click', () => {
        rows.splice(index, 1);
        update();
        renderRows();
      });

      line.append(keyInput, valueInput, remove);
      list.appendChild(line);
    });

    const add = document.createElement('button');
    add.textContent = `+ Add ${keyLabel.toLowerCase()}`;
    add.addEventListener('click', () => {
      if (options.onAddRow) {
        options.onAddRow({ rows, render: renderRows, update });
        return;
      }
      rows.push({ key: '', value: '' });
      renderRows();
    });
    list.appendChild(add);
  };

  renderRows();
  container.appendChild(list);
  return container;
}

function getDefaultCardType() {
  const cardTypeField = state.fields.find((item) => item.id === 'card_type');
  if (cardTypeField && cardTypeField.default) {
    return cardTypeField.default;
  }
  return 'standard';
}

function normalizeCardType(value) {
  return (value || '').toString().trim().toLowerCase();
}

function extrasForCardType(cardType) {
  const normalized = normalizeCardType(cardType);
  const availableExtras = state.cardTypeExtras || {};
  if (availableExtras[normalized]) {
    return availableExtras[normalized];
  }

  const match = Object.keys(availableExtras).find(
    (key) => normalizeCardType(key) === normalized
  );

  return match ? availableExtras[match] : [];
}

function openExtrasPicker(cardType, rows, renderRows, updateRows) {
  const modal = buildModal('Add extra option');
  addFloatingCloseButton(modal, 'Close extra option selector');

  const wrapper = document.createElement('div');
  wrapper.className = 'card-type-modal';

  const overview = document.createElement('div');
  overview.className = 'modal-section modal-section--muted';

  const heading = document.createElement('h3');
  heading.textContent = 'Choose an extra option';

  const helper = document.createElement('p');
  helper.className = 'helper-text';
  helper.textContent = `Pick from documented extras for ${cardType || 'the selected card type'} or add your own.`;

  const helperList = document.createElement('ul');
  helperList.className = 'modal-list';
  ['Avoid duplicates—the list only shows options not already added.', 'Extras are added with an empty value so you can fill them in next.', 'You can always add another custom key if you need it.'].forEach(
    (tip) => {
      const item = document.createElement('li');
      item.textContent = tip;
      helperList.appendChild(item);
    }
  );

  overview.append(heading, helper, helperList);

  const optionsWrapper = document.createElement('div');
  optionsWrapper.className = 'search-results card-type-results';

  const available = extrasForCardType(cardType);
  const existingKeys = rows.map((row) => normalizeCardType(row.key)).filter(Boolean);
  const remaining = available.filter((key) => !existingKeys.includes(normalizeCardType(key)));

  if (remaining.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'helper-text';
    empty.textContent =
      available.length === 0
        ? 'No documented extras for this card type. You can still add a custom key.'
        : 'All available extras have already been added.';
    optionsWrapper.appendChild(empty);
  }

  remaining.forEach((key) => {
    const option = document.createElement('button');
    option.type = 'button';
    option.className = 'card-type-option';
    option.textContent = key;
    option.addEventListener('click', () => {
      rows.push({ key, value: '' });
      updateRows();
      renderRows();
      closeModal(modal.element);
    });
    optionsWrapper.appendChild(option);
  });

  const customWrapper = document.createElement('div');
  customWrapper.className = 'card-type-custom modal-section';

  const customHeader = document.createElement('div');
  customHeader.className = 'modal-section__header';

  const customTitle = document.createElement('h3');
  customTitle.textContent = 'Add a custom extra';

  const customCopy = document.createElement('p');
  customCopy.className = 'helper-text';
  customCopy.textContent = 'Use a descriptive key so you and others know what it represents.';

  customHeader.append(customTitle, customCopy);

  const customLabel = document.createElement('p');
  customLabel.className = 'helper-text';
  customLabel.textContent = 'Need something else? Provide a custom extra key.';

  const customInput = document.createElement('input');
  customInput.type = 'text';
  customInput.placeholder = 'Custom extra key';

  const customButton = document.createElement('button');
  customButton.textContent = 'Add custom key';
  customButton.disabled = true;

  customInput.addEventListener('input', () => {
    customButton.disabled = customInput.value.trim() === '';
  });

  customButton.addEventListener('click', () => {
    const customValue = customInput.value.trim();
    if (!customValue) {
      return;
    }
    rows.push({ key: customValue, value: '' });
    updateRows();
    renderRows();
    closeModal(modal.element);
  });

  customWrapper.append(customHeader, customLabel, customInput, customButton);

  wrapper.append(overview, optionsWrapper, customWrapper);
  modal.content.appendChild(wrapper);
}

function extrasEditor(entry, field, value) {
  const cardType = getValue(entry.config, ['card_type']) || getDefaultCardType();
  return mapEditor(entry, field, value, 'Key', 'Value', undefined, {
    onAddRow: ({ rows, render, update }) => {
      openExtrasPicker(cardType, rows, render, update);
    },
  });
}

function seasonEditor(entry, field, value) {
  const seasons = { ...(value || {}) };
  const hideValue = seasons.hide;
  delete seasons.hide;
  const editor = mapEditor(entry, field, seasons, 'Season', 'Title', (map) => {
    const currentHide =
      getValue(entry.config, [...field.path, 'hide']) ?? hideValue;
    if (currentHide !== undefined) {
      map.hide = currentHide;
    }
  });
  if (hideValue !== undefined) {
    const current = getValue(entry.config, field.path) || {};
    current.hide = hideValue;
    updateField(entry, field, current);
  }
  return editor;
}

// -----------------------------------------------------------------------------
// Field manipulation helpers
// -----------------------------------------------------------------------------
function updateField(entry, field, value) {
  if (value === undefined) {
    removeField(entry, field);
    return;
  }
  setValue(entry.config, field.path, value);
}

function removeField(entry, field) {
  deleteValue(entry.config, field.path);
  renderEntries();
}

function getValue(object, path) {
  return path.reduce((acc, key) => (acc && acc[key] !== undefined ? acc[key] : undefined), object);
}

function setValue(object, path, value) {
  let cursor = object;
  for (let i = 0; i < path.length - 1; i += 1) {
    const key = path[i];
    if (cursor[key] === undefined || typeof cursor[key] !== 'object') {
      cursor[key] = {};
    }
    cursor = cursor[key];
  }
  cursor[path[path.length - 1]] = value;
}

function deleteValue(object, path) {
  let cursor = object;
  const stack = [];
  for (let i = 0; i < path.length - 1; i += 1) {
    const key = path[i];
    if (!cursor || typeof cursor[key] !== 'object') {
      return;
    }
    stack.push([cursor, key]);
    cursor = cursor[key];
  }
  delete cursor[path[path.length - 1]];

  // Cleanup empty objects
  for (let i = stack.length - 1; i >= 0; i -= 1) {
    const [parent, key] = stack[i];
    if (Object.keys(parent[key]).length === 0) {
      delete parent[key];
    }
  }
}

// -----------------------------------------------------------------------------
// Additional UI components
// -----------------------------------------------------------------------------
const BASICS_FIELDS = new Set([
  'library',
  'card_type',
  'episode_text_format',
  'episode_data_source',
  'watched_style',
  'unwatched_style',
  'image_source_priority',
]);

const ID_FIELDS = new Set([
  'tmdb_id',
  'tvdb_id',
  'imdb_id',
  'tvrage_id',
  'emby_id',
  'jellyfin_id',
  'sonarr_id',
]);

const TEXT_FIELDS = new Set(['translation']);

const FIELD_GROUP_DEFINITIONS = [
  {
    id: 'basics',
    label: 'Getting started',
    matcher: (field) => BASICS_FIELDS.has(field.id),
  },
  {
    id: 'font',
    label: 'Font & typography',
    matcher: (field) => field.path?.[0] === 'font',
  },
  {
    id: 'seasons',
    label: 'Seasons & episodes',
    matcher: (field) => field.path?.[0] === 'seasons' || field.id === 'episode_ranges',
  },
  {
    id: 'text',
    label: 'Text & localization',
    matcher: (field) => TEXT_FIELDS.has(field.id),
  },
  {
    id: 'identifiers',
    label: 'Metadata IDs',
    matcher: (field) => ID_FIELDS.has(field.id),
  },
];

const FIELD_DISPLAY_ORDER = [
  'library',
  'card_type',
  'episode_text_format',
  'episode_data_source',
  'watched_style',
  'unwatched_style',
  'image_source_priority',
  'font.file',
  'font.size',
  'font.color',
  'font.case',
  'font.vertical_shift',
  'font.interline_spacing',
  'font.interword_spacing',
  'font.kerning',
  'font.stroke_width',
  'font.validate',
  'font.replacements',
  'seasons.hide',
  'seasons.titles',
  'episode_ranges',
  'translation',
  'tmdb_id',
  'tvdb_id',
  'imdb_id',
  'tvrage_id',
  'emby_id',
  'jellyfin_id',
  'sonarr_id',
];

const FIELD_DISPLAY_ORDER_LOOKUP = FIELD_DISPLAY_ORDER.reduce((map, fieldId, index) => {
  map.set(fieldId, index);
  return map;
}, new Map());

const DEFAULT_FIELD_GROUP = { id: 'other', label: 'Other fields' };

function resolveFieldGroup(field) {
  const match = FIELD_GROUP_DEFINITIONS.find((group) => group.matcher(field));
  return match || DEFAULT_FIELD_GROUP;
}

function compareFieldOptions(a, b) {
  const orderA = FIELD_DISPLAY_ORDER_LOOKUP.get(a.id);
  const orderB = FIELD_DISPLAY_ORDER_LOOKUP.get(b.id);
  const hasOrderA = orderA !== undefined;
  const hasOrderB = orderB !== undefined;
  if (hasOrderA && hasOrderB) {
    return orderA - orderB;
  }
  if (hasOrderA) {
    return -1;
  }
  if (hasOrderB) {
    return 1;
  }
  return (a.label || '').localeCompare(b.label || '', undefined, { sensitivity: 'base' });
}

function createFieldOption(field, onSelect) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'field-option';

  const title = document.createElement('span');
  title.className = 'field-option__title';
  title.textContent = field.label;

  const meta = document.createElement('span');
  meta.className = 'field-option__meta';
  const fragments = [];
  if (field.type) {
    fragments.push(field.type);
  }
  if (field.path?.length) {
    fragments.push(field.path.join(' › '));
  }
  meta.textContent = fragments.join(' • ');

  button.append(title, meta);
  button.addEventListener('click', () => onSelect(field));
  return button;
}

function renderFieldGroups(container, fields, onSelect) {
  container.innerHTML = '';
  if (fields.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'helper-text';
    empty.textContent = 'No fields match your search.';
    container.appendChild(empty);
    return;
  }

  const grouped = new Map();
  fields.forEach((field) => {
    const groupMeta = resolveFieldGroup(field);
    if (!grouped.has(groupMeta.id)) {
      grouped.set(groupMeta.id, { ...groupMeta, fields: [] });
    }
    grouped.get(groupMeta.id).fields.push(field);
  });

  const orderedGroups = FIELD_GROUP_DEFINITIONS.map((definition) => grouped.get(definition.id)).filter(
    Boolean
  );
  if (grouped.has(DEFAULT_FIELD_GROUP.id)) {
    orderedGroups.push(grouped.get(DEFAULT_FIELD_GROUP.id));
  }

  orderedGroups.forEach((group) => {
    if (!group) {
      return;
    }
    const section = document.createElement('details');
    section.className = 'field-group';
    section.open = false;

    const summary = document.createElement('summary');
    summary.className = 'field-group__summary';
    const label = document.createElement('span');
    label.textContent = group.label;
    const count = document.createElement('span');
    count.className = 'field-group__count';
    count.textContent = group.fields.length;
    summary.append(label, count);

    const list = document.createElement('div');
    list.className = 'field-group__list';
    group.fields
      .sort((a, b) => compareFieldOptions(a, b))
      .forEach((field) => list.appendChild(createFieldOption(field, onSelect)));

    section.append(summary, list);
    container.appendChild(section);
  });
}

function openFieldSelector(entry) {
  const modal = buildModal('Add field');
  addFloatingCloseButton(modal, 'Close add field dialog');

  const available = state.fields
    .filter((field) => getValue(entry.config, field.path) === undefined)
    .sort((a, b) =>
      (a.label || '').localeCompare(b.label || '', undefined, { sensitivity: 'base' })
    );

  if (available.length === 0) {
    const message = document.createElement('p');
    message.textContent = 'All available options are already configured.';
    modal.content.appendChild(message);
  } else {
    const wrapper = document.createElement('div');
    wrapper.className = 'field-selector';

    const intro = document.createElement('div');
    intro.className = 'modal-section modal-section--muted';

    const introHeading = document.createElement('h3');
    introHeading.textContent = 'Add a new line to this entry';

    const introCopy = document.createElement('p');
    introCopy.className = 'helper-text';
    introCopy.textContent = 'Search by name or description to quickly find the field you need.';

    const introList = document.createElement('ul');
    introList.className = 'modal-list';
    ['Each category is collapsible so you can focus on what matters.', 'Searching filters across labels, types, and nested paths.', 'Select a field to add it with sensible defaults—you can edit it right after.'].forEach(
      (tip) => {
        const item = document.createElement('li');
        item.textContent = tip;
        introList.appendChild(item);
      }
    );

    intro.append(introHeading, introCopy, introList);

    const search = document.createElement('input');
    search.type = 'search';
    search.placeholder = 'Search fields...';
    search.className = 'modal-search';

    const status = document.createElement('p');
    status.className = 'helper-text field-selector__status';

    const controls = document.createElement('div');
    controls.className = 'field-selector__controls';
    controls.append(search, status);

    const groupsContainer = document.createElement('div');
    groupsContainer.className = 'field-groups';

    const emptyState = document.createElement('div');
    emptyState.className = 'empty-state field-selector__empty';
    emptyState.textContent = 'No fields match your search. Try a different term or clear the filter.';
    emptyState.hidden = true;

    const render = () => {
      const term = search.value.trim().toLowerCase();
      const filtered = available.filter((field) => {
        if (!term) {
          return true;
        }
        const haystack = [field.label, field.type, field.path?.join(' ') || '']
          .filter(Boolean)
          .join(' ')
          .toLowerCase();
        return haystack.includes(term);
      });
      status.textContent = `${filtered.length} of ${available.length} fields shown`;
      groupsContainer.innerHTML = '';
      emptyState.hidden = filtered.length > 0;
      if (filtered.length === 0) {
        return;
      }
      renderFieldGroups(groupsContainer, filtered, (field) => {
        const defaultValue = defaultValueForField(field);
        updateField(entry, field, defaultValue);
        closeModal(modal.element);
        renderEntries();
      });
    };

    search.addEventListener('input', render);
    render();

    wrapper.append(intro, controls, groupsContainer, emptyState);
    modal.content.appendChild(wrapper);
  }

  modal.footer.appendChild(closeButton(() => closeModal(modal.element)));
}

const fontFaceRegistry = new Map();

function registerFontPreviewFace(path) {
  if (!path) return null;
  if (fontFaceRegistry.has(path)) {
    return fontFaceRegistry.get(path);
  }

  const safeName = path.replace(/[^a-zA-Z0-9]/g, '_');
  const fontName = `fontPreview_${safeName}_${fontFaceRegistry.size}`;
  const fontUrl = `/api/fonts/file?path=${encodeURIComponent(path)}`;

  const style = document.createElement('style');
  style.textContent = `
    @font-face {
      font-family: '${fontName}';
      src: url('${fontUrl}');
    }
  `;
  document.head.appendChild(style);

  fontFaceRegistry.set(path, fontName);
  return fontName;
}

function openFontBrowser(entry, field, input) {
  const modal = buildModal('Select font');

  const pathDisplay = document.createElement('p');
  pathDisplay.className = 'helper-text';
  pathDisplay.textContent = state.fontDirectory;
  modal.content.appendChild(pathDisplay);

  const browser = document.createElement('div');
  browser.className = 'font-browser';

  const filesPanel = document.createElement('div');
  filesPanel.className = 'panel';
  const panelTitle = document.createElement('strong');
  panelTitle.textContent = 'Available fonts';
  filesPanel.appendChild(panelTitle);

  const fontGrid = document.createElement('div');
  fontGrid.className = 'font-grid';
  filesPanel.appendChild(fontGrid);

  browser.appendChild(filesPanel);
  modal.content.appendChild(browser);

  const renderFonts = (entries) => {
    fontGrid.innerHTML = '';
    const fonts = (entries || []).filter((fileEntry) => fileEntry.type === 'file');

    if (!fonts.length) {
      const empty = document.createElement('p');
      empty.className = 'font-grid__empty';
      empty.textContent = 'No fonts found in /config/fonts';
      fontGrid.appendChild(empty);
      return;
    }

    fonts.forEach((fileEntry) => {
      const tile = document.createElement('button');
      tile.type = 'button';
      tile.className = 'font-tile';
      tile.addEventListener('click', () => {
        input.value = fileEntry.path;
        updateField(entry, field, fileEntry.path);
        closeModal(modal.element);
      });

      const fontFace = registerFontPreviewFace(fileEntry.path);
      const preview = document.createElement('span');
      preview.className = 'font-tile__preview';
      if (fontFace) {
        preview.style.fontFamily = fontFace;
      }
      preview.textContent = 'AaBbCc 123';

      const name = document.createElement('span');
      name.className = 'font-tile__filename';
      name.textContent = fileEntry.name;

      tile.append(preview, name);
      fontGrid.appendChild(tile);
    });
  };

  const loadFonts = async () => {
    const response = await fetch(`/api/fonts?path=${encodeURIComponent(state.fontDirectory)}`);
    if (!response.ok) {
      showToast('Unable to load fonts', 'error');
      return;
    }
    const data = await response.json();
    pathDisplay.textContent = data.path;
    renderFonts(data.entries || []);
  };

  loadFonts();

  modal.footer.appendChild(closeButton(() => closeModal(modal.element)));
}

function PathParent(path) {
  if (!path) return null;
  const parts = path.split('/').filter(Boolean);
  if (parts.length === 0) return null;
  parts.pop();
  return `/${parts.join('/')}`;
}

async function uploadFont(file, targetDirectory) {
  const formData = new FormData();
  formData.append('file', file);
  if (targetDirectory) {
    formData.append('path', targetDirectory);
  }

  const response = await fetch('/api/fonts/upload', {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || 'Unable to upload font');
  }

  return response.json();
}

function openPreview(entry) {
  const modal = buildModal('Generating preview');
  const message = document.createElement('p');
  message.textContent = 'Creating preview, please wait...';
  modal.content.appendChild(message);

  fetch('/api/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: entry.name, config: entry.config, force: true }),
  })
    .then(async (response) => {
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || 'Preview failed');
      }
      return response.json();
    })
    .then((data) => {
      modal.content.innerHTML = '';
      const img = document.createElement('img');
      img.className = 'preview-image';
      img.src = `data:${data.mime};base64,${data.data}`;
      entry.previewSrc = img.src;
      entry.previewError = null;
      updatePreviewCache(entry);
      updateEntryPreview(entry);
      modal.content.appendChild(img);
    })
    .catch((error) => {
      modal.content.innerHTML = '';
      modal.content.textContent = error.message;
    });

  modal.footer.appendChild(closeButton(() => closeModal(modal.element)));
}

function removeEntry(entry) {
  if (!confirm(`Remove "${entry.name}"?`)) {
    return;
  }
  state.entries = state.entries.filter((item) => item !== entry);
  state.collapsedEntries.delete(entry.id);
  state.lastSavedEntries.delete(entry.id);
  renderEntries();
}

// -----------------------------------------------------------------------------
// Add entry modal
// -----------------------------------------------------------------------------
function openAddEntryModal() {
  const modal = buildModal('Add series entry');

  const form = document.createElement('div');
  form.className = 'modal-form';

  const nameField = document.createElement('input');
  nameField.type = 'text';
  nameField.placeholder = 'Series name (e.g. The Example Show (2024))';

  const searchInput = document.createElement('input');
  searchInput.type = 'search';
  searchInput.placeholder = 'Search Plex...';

  const searchButton = document.createElement('button');
  searchButton.textContent = 'Search';

  const resultsContainer = document.createElement('div');
  resultsContainer.className = 'search-results';

  form.appendChild(nameField);
  form.appendChild(document.createElement('hr'));
  form.appendChild(searchInput);
  form.appendChild(searchButton);
  form.appendChild(resultsContainer);

  modal.content.appendChild(form);

  let selectedResult = null;

  const performSearch = async () => {
    const query = searchInput.value.trim();
    if (!query) return;
    resultsContainer.innerHTML = '<p class="helper-text">Searching…</p>';
    try {
      const response = await fetch(`/api/plex/search?q=${encodeURIComponent(query)}`);
      if (!response.ok) throw new Error('Search failed');
      const data = await response.json();
      renderSearchResults(data.results || []);
    } catch (error) {
      resultsContainer.innerHTML = '';
      resultsContainer.textContent = error.message;
    }
  };

  searchButton.addEventListener('click', performSearch);
  searchInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      performSearch();
    }
  });

  const renderSearchResults = (results) => {
    resultsContainer.innerHTML = '';
    if (results.length === 0) {
      resultsContainer.textContent = 'No results.';
      return;
    }
    results.forEach((result) => {
      const item = document.createElement('div');
      item.className = 'search-result';
      const summary = document.createElement('div');
      const title = result.year ? `${result.title} (${result.year})` : result.title;
      summary.innerHTML = `<h3>${title}</h3><p class="helper-text">${
        result.library || 'Unknown library'
      }</p>`;

      const select = document.createElement('button');
      select.textContent = 'Select';
      select.addEventListener('click', () => {
        selectedResult = result;
        nameField.value = title;
        highlightSelection(item);
      });

      item.append(summary, select);
      resultsContainer.appendChild(item);
    });
  };

  const highlightSelection = (element) => {
    resultsContainer.querySelectorAll('.search-result').forEach((item) => {
      item.classList.remove('active');
    });
    element.classList.add('active');
  };

  modal.footer.appendChild(
    closeButton(() => {
      closeModal(modal.element);
    })
  );

  const createButton = document.createElement('button');
  createButton.className = 'accent';
  createButton.textContent = 'Create entry';
  createButton.addEventListener('click', () => {
    const name = nameField.value.trim();
    if (!name) {
      showToast('Series name is required', 'error');
      return;
    }
    if (state.entries.some((entry) => entry.name === name)) {
      showToast('A series with that name already exists', 'error');
      return;
    }

    state.filter = '';
    if (dom.search) {
      dom.search.value = '';
    }

    const config = {};
    const defaultLibrary = selectDefaultLibrary(selectedResult);
    if (defaultLibrary) {
      config.library = defaultLibrary;
    }
    config.card_type = 'standard';

    if (selectedResult && selectedResult.ids) {
      if (selectedResult.ids.tmdb_id) {
        const tmdb = Number(selectedResult.ids.tmdb_id);
        if (!Number.isNaN(tmdb)) config.tmdb_id = tmdb;
      }
      if (selectedResult.ids.tvdb_id) {
        const tvdb = Number(selectedResult.ids.tvdb_id);
        if (!Number.isNaN(tvdb)) config.tvdb_id = tvdb;
      }
      if (selectedResult.ids.imdb_id) config.imdb_id = selectedResult.ids.imdb_id;
    }

    const newEntry = {
      id: `${name}-${Date.now()}`,
      name,
      config,
    };
    state.entries.push(newEntry);
    setEntryCollapsed(newEntry.id, false);
    state.pendingEntryId = newEntry.id;
    sortEntries();

    closeModal(modal.element);
    renderEntries();
  });

  modal.footer.appendChild(createButton);
}

function selectDefaultLibrary(result) {
  const libraryNames = Object.keys(state.libraries || {});
  if (!libraryNames.length) return 'TV Shows';
  if (result && result.library && libraryNames.includes(result.library)) {
    return result.library;
  }
  return libraryNames.includes('TV Shows') ? 'TV Shows' : libraryNames[0];
}

// -----------------------------------------------------------------------------
// Saving configuration
// -----------------------------------------------------------------------------
function cloneData(value) {
  return JSON.parse(JSON.stringify(value ?? {}));
}

function snapshotEntry(entry) {
  return { name: entry.name, config: cloneData(entry.config) };
}

function deepEqualEntrySnapshots(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function hasEntryChangedSinceLastSave(entry) {
  const previous = state.lastSavedEntries.get(entry.id);
  if (!previous) {
    return true;
  }
  return !deepEqualEntrySnapshots(previous, snapshotEntry(entry));
}

function recordEntrySaveSnapshot(entry) {
  state.lastSavedEntries.set(entry.id, snapshotEntry(entry));
}

function syncSavedEntrySnapshots() {
  state.lastSavedEntries = new Map(
    state.entries.map((entry) => [entry.id, snapshotEntry(entry)])
  );
}

function loadPreviewCache() {
  try {
    const cached = localStorage.getItem(PREVIEW_CACHE_STORAGE_KEY);
    state.previewCache = cached ? JSON.parse(cached) : {};
  } catch (error) {
    console.warn('Failed to load preview cache', error);
    state.previewCache = {};
  }
}

function persistPreviewCache() {
  try {
    localStorage.setItem(
      PREVIEW_CACHE_STORAGE_KEY,
      JSON.stringify(state.previewCache)
    );
  } catch (error) {
    console.warn('Failed to persist preview cache', error);
  }
}

function previewCacheKey(entry) {
  return entry?.name || null;
}

function restoreCachedPreview(entry) {
  const key = previewCacheKey(entry);
  if (!key) {
    return;
  }
  const cached = state.previewCache[key];
  const snapshot = JSON.stringify(snapshotEntry(entry));
  if (cached && cached.snapshot === snapshot && cached.src) {
    entry.previewSrc = cached.src;
  }
}

function updatePreviewCache(entry) {
  const key = previewCacheKey(entry);
  if (!key || !entry.previewSrc) {
    return;
  }
  state.previewCache[key] = {
    snapshot: JSON.stringify(snapshotEntry(entry)),
    src: entry.previewSrc,
  };
  persistPreviewCache();
}

function clearPreviewCacheEntry(entry) {
  const key = previewCacheKey(entry);
  if (!key || !state.previewCache[key]) {
    return;
  }
  delete state.previewCache[key];
  persistPreviewCache();
}

async function saveConfiguration() {
  try {
    sortEntries();
    renderEntries();
    const changedEntries = state.entries.filter(hasEntryChangedSinceLastSave);
    const payload = {
      libraries: state.libraries,
      series: state.entries.map((entry) => ({
        name: entry.name,
        config: entry.config,
      })),
    };

    const response = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || 'Failed to save configuration');
    }

    showToast('Configuration saved', 'success');

    changedEntries.forEach((entry) => {
      clearPreviewCacheEntry(entry);
      invalidateEntryPreview(entry);
      recordEntrySaveSnapshot(entry);
    });
    requestEntryPreviews(changedEntries);
  } catch (error) {
    showToast(error.message, 'error');
  }
}

function sortEntries() {
  state.entries.sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
  );
}

// -----------------------------------------------------------------------------
// Modal helpers
// -----------------------------------------------------------------------------
function buildModal(title) {
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';

  const modal = document.createElement('div');
  modal.className = 'modal';

  const header = document.createElement('header');
  const heading = document.createElement('h2');
  heading.textContent = title;
  header.appendChild(heading);

  const content = document.createElement('div');
  const footer = document.createElement('footer');

  modal.append(header, content, footer);
  backdrop.appendChild(modal);
  dom.modals.appendChild(backdrop);

  return { element: backdrop, modal, header, content, footer };
}

function addFloatingCloseButton(modal, label = 'Close dialog') {
  const dismissButton = document.createElement('button');
  dismissButton.type = 'button';
  dismissButton.className = 'modal-close modal-close--floating';
  dismissButton.setAttribute('aria-label', label);
  dismissButton.innerHTML =
    '<svg viewBox="0 0 24 24" role="presentation" aria-hidden="true"><path d="M6.4 6.4a1 1 0 0 1 1.42 0L12 10.6l4.18-4.2a1 1 0 0 1 1.42 1.42L13.42 12l4.18 4.18a1 1 0 0 1-1.42 1.42L12 13.42l-4.18 4.18a1 1 0 0 1-1.42-1.42L10.6 12 6.4 7.82a1 1 0 0 1 0-1.42z" /></svg>';
  dismissButton.addEventListener('click', () => closeModal(modal.element));
  modal.modal.insertBefore(dismissButton, modal.modal.firstChild);
  return dismissButton;
}

function closeButton(onClick) {
  const button = document.createElement('button');
  button.textContent = 'Close';
  button.addEventListener('click', onClick);
  return button;
}

function closeModal(element) {
  hideCardTypePreview();
  element.remove();
}

// -----------------------------------------------------------------------------
// Toast notifications
// -----------------------------------------------------------------------------
function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  toastContainer.appendChild(toast);
  setTimeout(() => toast.remove(), 4500);
}

async function triggerServerAction(
  button,
  endpoint,
  successMessage,
  { workingLabel = 'Working...', refresh = true, payload, onSuccess } = {}
) {
  if (!button) {
    return;
  }

  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = workingLabel;

  try {
    const requestOptions = { method: 'POST' };

    if (payload !== undefined) {
      requestOptions.headers = { 'Content-Type': 'application/json' };
      requestOptions.body = JSON.stringify(payload);
    }

    const response = await fetch(endpoint, requestOptions);
    let responsePayload = {};
    try {
      responsePayload = await response.json();
    } catch (error) {
      // Ignore JSON parse errors for non-JSON responses
    }
    if (!response.ok) {
      throw new Error(responsePayload.error || 'Failed to run action');
    }

    if (refresh) {
      await loadConfiguration();
      renderEntries();
    }
    if (typeof onSuccess === 'function') {
      onSuccess(responsePayload);
    }
    showToast(successMessage, 'success');
  } catch (error) {
    const message = error?.message || 'Unable to run action';
    console.error('Action request failed', { endpoint, payload, error });
    showToast(message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

