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
  logoCache: {},
  cardTypeExtras: {},
  logoBackgrounds: new Map(),
  services: {
    tmdbEnabled: true,
    plexEnabled: true,
  },
  settings: {
    series_sync_interval_seconds: 45,
    preferences: {},
    tautulli: {
      url: '',
      api_key: '',
      verify_ssl: true,
    },
  },
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
  runBuilder: document.getElementById('run-builder'),
  unmatchedIssues: document.getElementById('unmatched-issues'),
  recents: document.getElementById('open-recents'),
  settings: document.getElementById('open-settings'),
  modals: document.getElementById('modals'),
};

const toastContainer = document.createElement('div');
toastContainer.className = 'toast-container';
document.body.appendChild(toastContainer);

const CLIENT_LOG_ENDPOINT = '/api/client-log';
const PREVIEW_CACHE_STORAGE_KEY = 'tcm-preview-cache';
const LOGO_BACKGROUND_STORAGE_KEY = 'tcm-logo-backgrounds';
const CACHE_DB_NAME = 'tcm-preview-cache';
const CACHE_DB_VERSION = 2;
const PREVIEW_DB_STORE = 'previews';
const LOGO_DB_STORE = 'logos';
const FONT_EXTENSIONS = ['.ttf', '.otf', '.woff', '.woff2', '.ttc'];

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

function sanitizePathName(value) {
  const replacements = {
    '?': '!',
    '<': '',
    '>': '',
    ':': ' -',
    '"': '',
    '|': '',
    '*': '-',
    '/': '+',
    '\\': '+',
  };

  return (value || '')
    .toString()
    .split('')
    .map((char) => (char in replacements ? replacements[char] : char))
    .join('');
}

function resolveEntrySlug(entry) {
  if (!entry) {
    return '';
  }

  if (entry.slug) {
    return entry.slug;
  }

  return sanitizePathName(entry.name || '');
}

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
    // Ensure the preview cache is ready before observers start requesting images.
    await loadPreviewCache();
    await loadLogoCache();
    loadLogoBackgroundPreferences();
    await loadMetadata();
    await loadSettings();
    await loadConfiguration();
    registerEvents();
    setSearchVisibility(false);
    renderEntries();
    requestEntryPreviews(state.entries, { preferExisting: true });
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
  state.services = data.services || state.services;
}

async function loadSettings() {
  try {
    const response = await fetch('/api/settings');
    if (!response.ok) {
      throw new Error('Unable to load settings');
    }
    const data = await response.json();
    state.settings = data || state.settings;
  } catch (error) {
    console.warn('Unable to load settings', error);
  }
}

function initializeEntryPreviewState(entry) {
  if (!entry) {
    return;
  }
  entry.previewEpisode = entry.previewEpisode || 'random';
  entry.previewEpisodeOptions = entry.previewEpisodeOptions || null;
  entry.previewEpisodeStatus = entry.previewEpisodeStatus || 'idle';
  entry.previewEpisodeError = entry.previewEpisodeError || null;
  entry.previewStale = false;
}

async function loadConfiguration() {
  const response = await fetch('/api/config');
  if (!response.ok) {
    throw new Error('Unable to load tv.yml');
  }
  const data = await response.json();
  state.libraries = data.libraries || {};
  state.entries = (data.series || []).map((entry, index) => {
    const mapped = {
      id: `${entry.name}-${index}`,
      name: entry.name,
      slug: entry.slug || sanitizePathName(entry.name),
      config: entry.config || {},
    };
    initializeEntryPreviewState(mapped);
    return mapped;
  });
  sortEntries();
  state.collapsedEntries = new Set(state.entries.map((entry) => entry.id));
  syncSavedEntrySnapshots();
  await Promise.all(
    state.entries.map((entry) =>
      Promise.all([restoreCachedLogo(entry), restoreCachedPreview(entry)])
    )
  );
}

async function saveSettings(payload) {
  const response = await fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || 'Unable to save settings');
  }

  const data = await response.json();
  state.settings = data || state.settings;
  return data;
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

  if (dom.unmatchedIssues) {
    dom.unmatchedIssues.addEventListener('click', () => openUnmatchedItemsModal());
  }

  if (dom.recents) {
    dom.recents.addEventListener('click', () => openRecentsModal());
  }

  if (dom.settings) {
    dom.settings.addEventListener('click', () => openSettingsModal());
  }
}

function openEntryActionsModal(entry, entryPayload) {
  const modal = buildModal(`Manage ${entry.name}`);
  addFloatingCloseButton(modal, `Close actions for ${entry.name}`);

  const description = document.createElement('p');
  description.className = 'helper-text';
  description.textContent = 'Choose an action to run for this series.';
  modal.content.appendChild(description);

  const actions = document.createElement('div');
  actions.className = 'entry-actions-modal';

  const downloadButton = document.createElement('button');
  downloadButton.textContent = 'Download sources';
  downloadButton.addEventListener('click', () =>
    triggerServerAction(
      downloadButton,
      '/api/actions/download-series-sources',
      `Downloaded sources for ${entry.name}`,
      { workingLabel: 'Downloading...', refresh: false, payload: entryPayload() }
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

  const deleteButton = document.createElement('button');
  deleteButton.className = 'danger';
  deleteButton.textContent = 'Delete cards';
  deleteButton.addEventListener('click', () =>
    triggerServerAction(
      deleteButton,
      '/api/actions/delete-series-cards',
      `Deleted cards for ${entry.name}`,
      { workingLabel: 'Deleting...', refresh: false, payload: entryPayload() }
    )
  );

  actions.append(downloadButton, revertButton, forgetButton, deleteButton);
  modal.content.appendChild(actions);

  const dismiss = closeButton(() => closeModal(modal.element));
  modal.footer.appendChild(dismiss);
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
  initializeEntryPreviewState(entry);

  const removeEntryButton = document.createElement('button');
  removeEntryButton.type = 'button';
  removeEntryButton.className = 'entry-remove';
  removeEntryButton.setAttribute('aria-label', `Remove ${entry.name}`);
  const removeEntryIcon = document.createElement('span');
  removeEntryIcon.className = 'material-symbols-rounded';
  removeEntryIcon.setAttribute('aria-hidden', 'true');
  removeEntryIcon.textContent = 'close';
  removeEntryButton.appendChild(removeEntryIcon);
  removeEntryButton.addEventListener('click', () => removeEntry(entry));
  container.appendChild(removeEntryButton);

  const header = document.createElement('div');
  header.className = 'entry-header';

  const summary = document.createElement('div');
  summary.className = 'entry-summary';

  const summaryBody = document.createElement('div');
  summaryBody.className = 'entry-summary__body';

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

  const logoWrapper = document.createElement('div');
  logoWrapper.className = 'entry-logo-wrapper';

  const logo = document.createElement('img');
  logo.className = 'entry-logo';
  logo.alt = `${entry.name} logo`;
  logo.loading = 'lazy';
  const logoBackgroundToggle = document.createElement('button');
  logoBackgroundToggle.type = 'button';
  logoBackgroundToggle.className = 'entry-logo-toggle';

  const logoBackgroundSwitch = document.createElement('span');
  logoBackgroundSwitch.className = 'entry-logo-toggle__switch';

  const logoBackgroundHandle = document.createElement('span');
  logoBackgroundHandle.className = 'entry-logo-toggle__handle';
  logoBackgroundSwitch.append(logoBackgroundHandle);
  logoBackgroundToggle.append(logoBackgroundSwitch);

  const syncLogoToggleVisibility = () => {
    logoBackgroundToggle.hidden = logo.classList.contains('entry-logo--missing');
  };

  const logoUrl = `/api/series-logo?name=${encodeURIComponent(entry.name)}`;

  const handleLogoError = () => {
    const hadCachedLogo = Boolean(entry.logoSrc);
    logo.classList.add('entry-logo--missing');
    logo.classList.remove('entry-logo--light', 'entry-logo--dark');
    logo.removeAttribute('src');
    syncLogoToggleVisibility();
    void clearLogoCacheEntry(entry);
    if (hadCachedLogo) {
      logo.src = logoUrl;
    }
  };

  logo.addEventListener('load', () => {
    applyLogoStroke(logo);
    syncLogoToggleVisibility();
    void updateLogoCacheFromElement(entry, logo);
  });
  logo.addEventListener('error', handleLogoError);
  if (entry.logoSrc) {
    logo.src = entry.logoSrc;
  } else {
    logo.src = logoUrl;
  }

  if (logo.complete) {
    if (logo.naturalWidth > 0 && logo.naturalHeight > 0) {
      applyLogoStroke(logo);
    } else {
      handleLogoError();
    }
  }

  const syncLogoBackground = () => {
    const isDarkBackground = getLogoBackgroundPreference(entry.name) === 'dark';
    logo.classList.toggle('entry-logo--dark-surface', isDarkBackground);
    logoBackgroundToggle.dataset.mode = isDarkBackground ? 'dark' : 'light';
    logoBackgroundToggle.setAttribute('aria-pressed', String(isDarkBackground));
    const toggleLabel = isDarkBackground
      ? 'Switch logo background to light'
      : 'Switch logo background to dark';
    logoBackgroundToggle.setAttribute('aria-label', toggleLabel);
    logoBackgroundToggle.title = toggleLabel;
  };

  logoBackgroundToggle.addEventListener('click', () => {
    const nextMode = getLogoBackgroundPreference(entry.name) === 'dark' ? 'light' : 'dark';
    setLogoBackgroundPreference(entry.name, nextMode);
    syncLogoBackground();
  });

  syncLogoBackground();
  syncLogoToggleVisibility();

  logoWrapper.append(logoBackgroundToggle, logo);

  const preview = document.createElement('div');
  preview.className = 'entry-preview';
  preview.dataset.entryId = entry.id;

  const previewImage = document.createElement('img');
  previewImage.className = 'entry-preview__image';
  previewImage.alt = `${entry.name} preview`;

  const previewPlaceholder = document.createElement('span');
  previewPlaceholder.className = 'entry-preview__placeholder';
  previewPlaceholder.textContent = 'Loading preview...';

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
  media.append(logoWrapper, preview);

  const titleInput = document.createElement('input');
  titleInput.type = 'text';
  titleInput.value = entry.name;
  titleInput.addEventListener('input', (event) => {
    entry.name = event.target.value;
  });
  titleInput.addEventListener('focus', () => {
    titleInput.dataset.originalName = entry.name;
  });
  titleInput.addEventListener('blur', () => {
    const originalName = titleInput.dataset.originalName;
    if (originalName && originalName !== entry.name) {
      moveLogoBackgroundPreference(originalName, entry.name);
      syncLogoBackground();
    }
    sortEntries();
    state.pendingEntryId = entry.id;
    renderEntries();
  });

  const titleContainer = document.createElement('div');
  titleContainer.className = 'entry-title';
  titleContainer.appendChild(titleInput);

  summaryBody.append(titleContainer, media);
  summary.append(toggleButton, summaryBody);
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

  const previewEpisodeControl = document.createElement('div');
  previewEpisodeControl.className = 'preview-episode-control';

  const previewEpisodeLabel = document.createElement('span');
  previewEpisodeLabel.className = 'preview-episode-label';
  previewEpisodeLabel.textContent = 'Preview episode';

  const previewEpisodeSelect = document.createElement('select');
  previewEpisodeSelect.className = 'preview-episode-select';
  previewEpisodeSelect.setAttribute('aria-label', 'Select preview episode');

  const previewEpisodeStatus = document.createElement('span');
  previewEpisodeStatus.className = 'preview-episode-status helper-text';
  previewEpisodeStatus.hidden = true;
  previewEpisodeStatus.addEventListener('click', () => {
    if (entry.previewEpisodeStatus === 'error') {
      entry.previewEpisodeStatus = 'idle';
      syncPreviewEpisodeControls();
      ensurePreviewEpisodes(entry, syncPreviewEpisodeControls);
    }
  });

  const syncPreviewEpisodeControls = () => {
    previewEpisodeSelect.innerHTML = '';

    const randomOption = document.createElement('option');
    randomOption.value = 'random';
    randomOption.textContent = 'Random episode';
    previewEpisodeSelect.appendChild(randomOption);

    (entry.previewEpisodeOptions || []).forEach((option) => {
      const choice = document.createElement('option');
      choice.value = option.key;
      choice.textContent = option.label || option.key;
      previewEpisodeSelect.appendChild(choice);
    });

    previewEpisodeSelect.value = entry.previewEpisode || 'random';
    if (!previewEpisodeSelect.value) {
      previewEpisodeSelect.value = 'random';
    }

    const statusText =
      entry.previewEpisodeStatus === 'loading'
        ? 'Loading episodes…'
        : entry.previewEpisodeStatus === 'error'
          ? entry.previewEpisodeError || 'Unable to load episodes'
          : '';

    previewEpisodeStatus.textContent = statusText;
    previewEpisodeStatus.title =
      entry.previewEpisodeStatus === 'error' ? 'Click to retry loading episodes' : '';
    previewEpisodeStatus.hidden = !statusText;
    previewEpisodeSelect.disabled = entry.previewEpisodeStatus === 'loading';
  };

  previewEpisodeSelect.addEventListener('change', async () => {
    entry.previewEpisode = previewEpisodeSelect.value || 'random';
    await invalidateEntryPreview(entry);
    loadEntryPreview(entry);
  });

  previewEpisodeControl.append(
    previewEpisodeLabel,
    previewEpisodeSelect,
    previewEpisodeStatus
  );

  const previewButton = document.createElement('button');
  previewButton.textContent = 'Preview';
  previewButton.addEventListener('click', () => openPreview(entry));

  const previewControls = document.createElement('div');
  previewControls.className = 'preview-controls';
  previewControls.append(previewEpisodeControl, previewButton);

  syncPreviewEpisodeControls();
  ensurePreviewEpisodes(entry, syncPreviewEpisodeControls);

  const manageButton = document.createElement('button');
  manageButton.className = 'icon-button entry-action-settings';
  manageButton.setAttribute('aria-label', `Open actions for ${entry.name}`);
  manageButton.innerHTML =
    '<span class="material-symbols-rounded" aria-hidden="true">settings</span>';
  manageButton.addEventListener('click', () =>
    openEntryActionsModal(entry, entryPayload)
  );

  actions.append(buildButton, manageButton, previewControls);
  header.append(summary, actions);

  const body = document.createElement('div');
  body.className = 'entry-body';

  const usedFields = new Set();
  const fontFieldRows = [];
  let extrasFieldRow = null;
  let extrasFieldDefinition = null;
  state.fields.forEach((field) => {
    const value = getValue(entry.config, field.path);
    if (field.id === 'extras') {
      extrasFieldDefinition = field;
    }
    if (value !== undefined) {
      usedFields.add(field.id);
      if (field.path?.[0] === 'font') {
        fontFieldRows.push(renderFieldRow(entry, field, value));
      } else if (field.id === 'extras') {
        extrasFieldRow = renderFieldRow(entry, field, value);
      } else {
        body.appendChild(renderFieldRow(entry, field, value));
      }
    }
  });

  const addLineButton = document.createElement('button');
  addLineButton.className = 'add-line';
  addLineButton.textContent = '+ Add line';
  addLineButton.addEventListener('click', () =>
    openFieldSelector(entry, {
      availableFilter: (field) => field.path?.[0] !== 'font' && field.id !== 'extras',
    })
  );
  body.appendChild(addLineButton);

  const extrasSection = document.createElement('section');
  extrasSection.className = 'entry-section entry-section--extras';

  const extrasHeader = document.createElement('div');
  extrasHeader.className = 'entry-section__header';

  const extrasTitle = document.createElement('h3');
  extrasTitle.className = 'entry-section__title';
  extrasTitle.textContent = 'Extra card options';

  extrasHeader.appendChild(extrasTitle);

  const extrasFieldsContainer = document.createElement('div');
  extrasFieldsContainer.className = 'entry-section__fields';

  const enableExtras = () => {
    if (!extrasFieldDefinition) {
      return;
    }
    const defaultValue = defaultValueForField(extrasFieldDefinition);
    setValue(entry.config, extrasFieldDefinition.path, defaultValue);
    renderEntries();
  };

  if (extrasFieldRow) {
    extrasFieldsContainer.appendChild(extrasFieldRow);
  } else if (extrasFieldDefinition) {
    const helper = document.createElement('p');
    helper.className = 'helper-text entry-section__empty';
    helper.textContent = 'No extra options added yet. Add an extra to customize your card.';

    const addExtrasButton = document.createElement('button');
    addExtrasButton.className = 'add-line add-line--inline';
    addExtrasButton.textContent = '+ Add extra option';
    addExtrasButton.addEventListener('click', () => enableExtras());

    extrasHeader.appendChild(addExtrasButton);
    extrasFieldsContainer.appendChild(helper);
  }

  extrasSection.append(extrasHeader, extrasFieldsContainer);
  body.appendChild(extrasSection);

  const fontSection = document.createElement('section');
  fontSection.className = 'entry-section entry-section--font';

  const fontHeader = document.createElement('div');
  fontHeader.className = 'entry-section__header';

  const fontTitle = document.createElement('h3');
  fontTitle.className = 'entry-section__title';
  fontTitle.textContent = 'Font';

  const addFontLineButton = document.createElement('button');
  addFontLineButton.className = 'add-line add-line--inline';
  addFontLineButton.textContent = '+ Add font line';
  addFontLineButton.addEventListener('click', () =>
    openFieldSelector(entry, {
      title: 'Add font line',
      introHeadingText: 'Add a new font option',
      introCopyText: 'Search across font settings to adjust typography for this card.',
      tips: [
        'Font file controls the typeface used for the card.',
        'Size, color, spacing, and casing let you fine-tune typography.',
        'You can revisit this menu anytime to add more font controls.',
      ],
      emptyMessage: 'All font options are already configured for this entry.',
      availableFilter: (field) => field.path?.[0] === 'font',
    })
  );

  fontHeader.append(fontTitle, addFontLineButton);

  const fontFieldsContainer = document.createElement('div');
  fontFieldsContainer.className = 'entry-section__fields';
  if (fontFieldRows.length === 0) {
    const helper = document.createElement('p');
    helper.className = 'helper-text entry-section__empty';
    helper.textContent = 'No font options added yet. Add lines to configure typography.';
    fontFieldsContainer.appendChild(helper);
  } else {
    fontFieldRows.forEach((row) => fontFieldsContainer.appendChild(row));
  }

  fontSection.append(fontHeader, fontFieldsContainer);
  body.appendChild(fontSection);

  container.append(header, body);
  return container;
}

let previewObserver = null;
const previewLoadOptions = new WeakMap();

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
    const statusText =
      entry.previewLoadingStrategy === 'generate'
        ? 'Generating preview...'
        : 'Loading preview...';
    placeholder.textContent = statusText;
  }

  if (entry.previewError && placeholder) {
    placeholder.textContent = entry.previewError;
    wrapper.classList.add('entry-preview--error');
  }
}

function ensurePreviewObserver() {
  if (previewObserver) {
    return previewObserver;
  }

  previewObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((observerEntry) => {
        if (!observerEntry.isIntersecting) {
          return;
        }

        const target = observerEntry.target;
        const entryId = target.dataset.entryId;
        const match = state.entries.find((candidate) => candidate.id === entryId);
        const options = previewLoadOptions.get(target) || {};

        if (match) {
          void loadEntryPreview(match, options);
        }

        previewLoadOptions.delete(target);
        previewObserver?.unobserve(target);
      });
    },
    { root: null, rootMargin: '400px 0px' }
  );

  return previewObserver;
}

function observeEntryPreview(entry, options = {}) {
  if (
    !entry ||
    entry.previewLoading ||
    (entry.previewSrc && !entry.previewStale)
  ) {
    return;
  }

  const wrapper = dom.entries.querySelector(
    `[data-entry-id="${entry.id}"] .entry-preview`
  );
  if (!wrapper) {
    return;
  }

  const observer = ensurePreviewObserver();
  previewLoadOptions.set(wrapper, options);
  observer.observe(wrapper);
}

function previewSeasonForEntry(entry, previewEpisodeKey) {
  if (!entry || !previewEpisodeKey || previewEpisodeKey === 'random') {
    return null;
  }

  const match = (entry.previewEpisodeOptions || []).find(
    (option) => option.key === previewEpisodeKey
  );

  if (match && (match.season || match.season === 0)) {
    return match.season;
  }

  return null;
}

async function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result?.toString() || null);
    reader.onerror = () => reject(new Error('Unable to read preview image'));
    reader.readAsDataURL(blob);
  });
}

async function fetchStaticPreview(entry, options = {}) {
  const { season = null } = options;
  const slug = resolveEntrySlug(entry);
  const params = new URLSearchParams();
  if (slug) {
    params.set('slug', slug);
  }
  if (entry?.name) {
    params.set('name', entry.name);
  }
  if (season || season === 0) {
    params.set('season', season);
  }

  if ([...params.keys()].length === 0) {
    return null;
  }

  params.set('_', Date.now().toString());

  try {
    const response = await fetch(`/api/preview/static?${params.toString()}`, {
      cache: 'no-store',
    });

    if (!response.ok) {
      return null;
    }

    const blob = await response.blob();
    return await blobToDataUrl(blob);
  } catch (error) {
    console.warn('Static preview lookup failed', error);
    return null;
  }
}

async function invalidateEntryPreview(entry) {
  entry.previewSrc = null;
  entry.previewError = null;
  entry.previewLoading = false;
  entry.previewLoadingStrategy = undefined;
  entry.previewStale = false;
  await clearPreviewCacheEntry(entry);
  updateEntryPreview(entry);
  observeEntryPreview(entry);
}

async function loadEntryPreview(entry, options = {}) {
  const { preferExisting = true } = options;
  if (
    !entry ||
    entry.previewLoading ||
    (entry.previewSrc && !entry.previewStale)
  ) {
    return;
  }

  entry.previewLoading = true;
  entry.previewLoadingStrategy = preferExisting ? 'load' : 'generate';
  const requestId = (entry.previewRequestId || 0) + 1;
  entry.previewRequestId = requestId;
  entry.previewError = null;
  updateEntryPreview(entry);
  const previewEpisode =
    entry.previewEpisode && entry.previewEpisode !== 'random'
      ? entry.previewEpisode
      : null;

  const previewSeason = previewSeasonForEntry(entry, previewEpisode);

  try {
    const staticPreview = await fetchStaticPreview(entry, { season: previewSeason });
    if (entry.previewRequestId === requestId && staticPreview) {
      entry.previewSrc = staticPreview;
      entry.previewError = null;
      entry.previewLoading = false;
      entry.previewLoadingStrategy = undefined;
      await updatePreviewCache(entry);
      updateEntryPreview(entry);
      return;
    }
  } catch (error) {
    console.warn('Static preview unavailable', error);
  }

  try {
    const response = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: entry.name,
        slug: resolveEntrySlug(entry),
        season: previewSeason,
        config: entry.config,
        preferExisting,
        previewEpisode,
      }),
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
      await updatePreviewCache(entry);
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
      entry.previewLoadingStrategy = undefined;
      updateEntryPreview(entry);
    }
  }
}

function requestEntryPreviews(entries = state.entries, options = {}) {
  entries.forEach((entry) => {
    observeEntryPreview(entry, options);
  });
}

async function refreshEntryPreviews(entries = state.entries) {
  await Promise.all(entries.map((entry) => invalidateEntryPreview(entry)));
  requestEntryPreviews(entries);
}

async function fetchPreviewEpisodes(entry, onUpdate) {
  if (!entry || entry.previewEpisodeStatus === 'loading') {
    return;
  }

  entry.previewEpisodeStatus = 'loading';
  if (onUpdate) {
    onUpdate();
  }

  try {
    const response = await fetch('/api/preview/episodes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: entry.name, config: entry.config }),
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || 'Unable to load episodes');
    }

    entry.previewEpisodeOptions = payload.episodes || [];
    entry.previewEpisodeStatus = 'loaded';
    entry.previewEpisodeError = null;
  } catch (error) {
    entry.previewEpisodeOptions = [];
    entry.previewEpisodeStatus = 'error';
    entry.previewEpisodeError = error.message || 'Unable to load episodes';
  } finally {
    if (onUpdate) {
      onUpdate();
    }
  }
}

function ensurePreviewEpisodes(entry, onUpdate) {
  if (!entry) {
    return;
  }
  if (entry.previewEpisodeStatus === 'loaded' || entry.previewEpisodeStatus === 'error') {
    return;
  }

  void fetchPreviewEpisodes(entry, onUpdate);
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

function loadLogoBackgroundPreferences() {
  try {
    const stored = localStorage.getItem(LOGO_BACKGROUND_STORAGE_KEY);
    const parsed = stored ? JSON.parse(stored) : {};
    state.logoBackgrounds = new Map(Object.entries(parsed));
  } catch (error) {
    state.logoBackgrounds = new Map();
  }
}

function persistLogoBackgroundPreferences() {
  try {
    const serialized = JSON.stringify(Object.fromEntries(state.logoBackgrounds));
    localStorage.setItem(LOGO_BACKGROUND_STORAGE_KEY, serialized);
  } catch (error) {
    // Ignore storage errors
  }
}

function getLogoBackgroundPreference(entryName) {
  return state.logoBackgrounds.get(entryName) || 'light';
}

function setLogoBackgroundPreference(entryName, preference) {
  if (!entryName) {
    return;
  }
  const mode = preference === 'dark' ? 'dark' : 'light';
  state.logoBackgrounds.set(entryName, mode);
  persistLogoBackgroundPreferences();
}

function moveLogoBackgroundPreference(oldName, newName) {
  if (!oldName || !newName || oldName === newName) {
    return;
  }
  const existing = state.logoBackgrounds.get(oldName);
  if (!existing) {
    return;
  }
  state.logoBackgrounds.delete(oldName);
  state.logoBackgrounds.set(newName, existing);
  persistLogoBackgroundPreferences();
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

  const browse = document.createElement('button');
  browse.type = 'button';
  browse.textContent = 'Browse';
  browse.addEventListener('click', () => {
    openFontPickerModal({
      initialPath: PathParent(input.value) || state.fontDirectory,
      onSelect: (path) => {
        input.value = path;
        updateField(entry, field, path);
      },
    });
  });

  wrapper.append(input, uploadInput, upload, browse);
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

      const friendlyLabel = options.formatKeyLabel ? options.formatKeyLabel(row.key) : null;

      const keyInput = document.createElement('input');
      keyInput.type = 'text';
      keyInput.placeholder = friendlyLabel || keyLabel;
      keyInput.value = row.key;
      keyInput.title = friendlyLabel || row.key || keyLabel;
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

      const keyColumn = document.createElement('div');
      keyColumn.className = 'table-list-row__key';
      if (friendlyLabel) {
        const labelElement = document.createElement('div');
        labelElement.className = 'table-list-row__label';
        labelElement.textContent = friendlyLabel;
        keyColumn.appendChild(labelElement);
      }

      if (options.showRawKeyHint && row.key) {
        const hint = document.createElement('div');
        hint.className = 'table-list-row__hint';
        hint.textContent = row.key;
        keyColumn.appendChild(hint);
      }

      keyColumn.appendChild(keyInput);

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

      line.append(keyColumn, valueInput, remove);
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

function formatExtraLabel(key) {
  if (!key) {
    return 'Custom extra';
  }

  const parts = key
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1));

  return parts.join(' ');
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
    option.textContent = formatExtraLabel(key);
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
    formatKeyLabel: formatExtraLabel,
    showRawKeyHint: true,
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

function openFieldSelector(
  entry,
  {
    title = 'Add field',
    introHeadingText = 'Add a new line to this entry',
    introCopyText = 'Search by name or description to quickly find the field you need.',
    tips = [
      'Each category is collapsible so you can focus on what matters.',
      'Searching filters across labels, types, and nested paths.',
      'Select a field to add it with sensible defaults—you can edit it right after.',
    ],
    emptyMessage = 'All available options are already configured.',
    availableFilter,
  } = {}
) {
  const modal = buildModal(title);
  addFloatingCloseButton(modal, 'Close add field dialog');

  const available = state.fields
    .filter((field) => !availableFilter || availableFilter(field))
    .filter((field) => getValue(entry.config, field.path) === undefined)
    .sort((a, b) =>
      (a.label || '').localeCompare(b.label || '', undefined, { sensitivity: 'base' })
    );

  if (available.length === 0) {
    const message = document.createElement('p');
    message.textContent = emptyMessage;
    modal.content.appendChild(message);
  } else {
    const wrapper = document.createElement('div');
    wrapper.className = 'field-selector';

    const intro = document.createElement('div');
    intro.className = 'modal-section modal-section--muted';

    const introHeading = document.createElement('h3');
    introHeading.textContent = introHeadingText;

    const introCopy = document.createElement('p');
    introCopy.className = 'helper-text';
    introCopy.textContent = introCopyText;

    const introList = document.createElement('ul');
    introList.className = 'modal-list';
    tips.forEach((tip) => {
      const item = document.createElement('li');
      item.textContent = tip;
      introList.appendChild(item);
    });

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

const fontPreviewCache = new Map();

function loadFontPreview(path) {
  if (!path) return Promise.resolve(null);
  if (fontPreviewCache.has(path)) {
    return fontPreviewCache.get(path);
  }

  const fontId = `font-${btoa(path).replace(/=+$/g, '')}`;
  const previewUrl = `/api/fonts/file?path=${encodeURIComponent(path)}`;
  const loader = new FontFace(fontId, `url('${previewUrl}')`, { style: 'normal', weight: '400' })
    .load()
    .then((loaded) => {
      document.fonts.add(loaded);
      return fontId;
    })
    .catch((error) => {
      console.warn('Unable to load font preview', { path, error });
      return null;
    });

  fontPreviewCache.set(path, loader);
  return loader;
}

function openFontPickerModal({ initialPath, onSelect }) {
  const modal = buildModal('Choose font file');
  addFloatingCloseButton(modal, 'Close font picker');

  const status = document.createElement('p');
  status.className = 'font-picker-status helper-text';

  const header = document.createElement('div');
  header.className = 'font-picker-header';

  const location = document.createElement('div');
  location.className = 'font-picker-path';

  const actions = document.createElement('div');
  actions.className = 'font-picker-actions';

  const up = document.createElement('button');
  up.type = 'button';
  up.textContent = 'Up one level';
  up.addEventListener('click', () => {
    const parent = PathParent(currentPath);
    if (parent) {
      renderDirectory(parent);
    }
  });

  const refresh = document.createElement('button');
  refresh.type = 'button';
  refresh.textContent = 'Refresh';
  refresh.addEventListener('click', () => renderDirectory(currentPath));

  actions.append(up, refresh);
  header.append(location, actions);

  const grid = document.createElement('div');
  grid.className = 'font-picker-grid';

  modal.content.append(header, status, grid);
  modal.footer.appendChild(closeButton(() => closeModal(modal.element)));

  let currentPath = initialPath || state.fontDirectory;

  const setStatus = (message, tone = 'muted') => {
    status.textContent = message;
    status.dataset.tone = tone;
  };

  const renderEntries = (entries) => {
    grid.innerHTML = '';
    if (!entries.length) {
      setStatus('No items found in this directory.', 'warning');
      return;
    }

    setStatus('Tap a font to select it.');

    const directories = entries.filter((entry) => entry.type === 'directory');
    const files = entries.filter((entry) => entry.type === 'file');

    directories.forEach((entry) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'font-card font-card--directory';
      card.innerHTML = `<div class="font-card__meta"><div class="font-card__icon">📁</div><div class="font-card__name">${entry.name}</div><div class="font-card__hint">Open folder</div></div>`;
      card.addEventListener('click', () => renderDirectory(entry.path));
      grid.appendChild(card);
    });

    files
      .filter((entry) => FONT_EXTENSIONS.some((ext) => entry.name.toLowerCase().endsWith(ext)))
      .forEach((entry) => {
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'font-card font-card--file';

        const preview = document.createElement('div');
        preview.className = 'font-card__preview';
        preview.textContent = 'Loading preview…';

        const meta = document.createElement('div');
        meta.className = 'font-card__meta';

        const title = document.createElement('div');
        title.className = 'font-card__name';
        title.textContent = entry.name;

        const hint = document.createElement('div');
        hint.className = 'font-card__hint';
        hint.textContent = 'Tap to use this font';

        meta.append(title, hint);
        card.append(preview, meta);

        card.addEventListener('click', () => {
          if (typeof onSelect === 'function') {
            onSelect(entry.path);
          }
          closeModal(modal.element);
        });

        loadFontPreview(entry.path, entry.name).then((fontId) => {
          if (!fontId) {
            preview.textContent = 'Preview unavailable';
            preview.classList.add('font-card__preview--fallback');
            return;
          }
          preview.textContent = 'Aa Bb Cc 0123';
          preview.style.fontFamily = `'${fontId}', 'Inter', system-ui, sans-serif`;
        });

        grid.appendChild(card);
      });
  };

  const renderDirectory = async (targetPath) => {
    try {
      setStatus('Loading fonts…');
      const response = await fetch(`/api/fonts?path=${encodeURIComponent(targetPath)}`);
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(data.error || 'Unable to browse fonts');
      }

      currentPath = data.path || targetPath;
      location.textContent = currentPath;
      up.disabled = currentPath === state.fontDirectory;
      renderEntries(data.entries || []);
    } catch (error) {
      console.error('Unable to load font directory', error);
      setStatus('Unable to load this directory. Please try again.', 'error');
      grid.innerHTML = '';
    }
  };

  renderDirectory(currentPath);
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

async function openPreview(entry) {
  const modal = buildModal('Generating preview');
  addFloatingCloseButton(modal, 'Close preview dialog');
  const message = document.createElement('p');
  message.textContent = 'Creating preview, please wait...';
  modal.content.appendChild(message);

  const previewEpisode =
    entry.previewEpisode && entry.previewEpisode !== 'random'
      ? entry.previewEpisode
      : null;

  const previewSeason = previewSeasonForEntry(entry, previewEpisode);

  try {
    const response = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: entry.name,
        slug: resolveEntrySlug(entry),
        season: previewSeason,
        config: entry.config,
        force: true,
        preferExisting: false,
        previewEpisode,
      }),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || 'Preview failed');
    }

    modal.content.innerHTML = '';
    const img = document.createElement('img');
    img.className = 'preview-image';
    img.src = `data:${data.mime};base64,${data.data}`;
    entry.previewSrc = img.src;
    entry.previewError = null;
    await updatePreviewCache(entry);
    updateEntryPreview(entry);
    modal.content.appendChild(img);
  } catch (error) {
    console.warn('Preview generation failed, attempting static preview', error);
    try {
      const staticPreview = await fetchStaticPreview(entry, { season: previewSeason });
      if (staticPreview) {
        modal.content.innerHTML = '';
        const img = document.createElement('img');
        img.className = 'preview-image';
        img.src = staticPreview;
        entry.previewSrc = img.src;
        entry.previewError = null;
        await updatePreviewCache(entry);
        updateEntryPreview(entry);
        modal.content.appendChild(img);
        return;
      }
    } catch (staticError) {
      console.warn('Static preview unavailable', staticError);
    }

    modal.content.innerHTML = '';
    modal.content.textContent = error.message;
  }

  modal.footer.appendChild(closeButton(() => closeModal(modal.element)));
}

function removeEntry(entry) {
  if (!confirm(`Remove "${entry.name}"?`)) {
    return;
  }
  state.entries = state.entries.filter((item) => item !== entry);
  state.collapsedEntries.delete(entry.id);
  state.lastSavedEntries.delete(entry.id);
  state.logoBackgrounds.delete(entry.name);
  void clearLogoCacheEntry(entry);
  persistLogoBackgroundPreferences();
  renderEntries();
}

// -----------------------------------------------------------------------------
// Unmatched metadata modal
// -----------------------------------------------------------------------------
const TMDB_ID_PATTERN = /^\d+$/;

function isServiceEnabled(service) {
  return state.services?.[service] !== false;
}

function hasValue(value) {
  if (value === undefined || value === null) {
    return false;
  }
  return String(value).trim().length > 0;
}

function isValidTmdbId(value) {
  if (value === undefined || value === null) {
    return false;
  }
  return TMDB_ID_PATTERN.test(String(value));
}

function isTmdbMissing(entry) {
  if (!isServiceEnabled('tmdbEnabled')) {
    return false;
  }
  return !isValidTmdbId(entry?.config?.tmdb_id);
}

function isPlexMissing(entry) {
  if (!isServiceEnabled('plexEnabled')) {
    return false;
  }
  const { config } = entry || {};
  if (!config || !hasValue(config.library)) {
    return true;
  }
  return !hasValue(config.rating_key);
}

function findUnmatchedEntries() {
  return state.entries
    .map((entry) => ({
      entry,
      tmdbMissing: isTmdbMissing(entry),
      plexMissing: isPlexMissing(entry),
    }))
    .filter(({ tmdbMissing, plexMissing }) => tmdbMissing || plexMissing);
}

function statusPill(text, tone = 'muted') {
  const pill = document.createElement('span');
  pill.className = `status-pill status-pill--${tone}`;
  pill.textContent = text;
  return pill;
}

function applyLibraryValue(entry, value) {
  if (!hasValue(value)) {
    delete entry.config.library;
    return;
  }
  entry.config.library = value;
}

function applyTmdbValue(entry, rawValue) {
  const value = rawValue.trim();
  if (!value) {
    delete entry.config.tmdb_id;
    return { valid: true };
  }

  if (!TMDB_ID_PATTERN.test(value)) {
    return { valid: false, message: 'TMDb ID must be numeric' };
  }

  entry.config.tmdb_id = Number.parseInt(value, 10);
  return { valid: true };
}

function applyRatingKeyValue(entry, rawValue) {
  const value = rawValue.trim();
  if (!value) {
    delete entry.config.rating_key;
    return;
  }

  const numeric = Number(value);
  entry.config.rating_key = Number.isFinite(numeric) ? numeric : value;
}

function buildUnmatchedRow(entry, onResolved) {
  const row = document.createElement('div');
  row.className = 'unmatched-row';

  entry.config = entry.config || {};

  const header = document.createElement('div');
  header.className = 'unmatched-row__header';

  const title = document.createElement('div');
  title.className = 'unmatched-row__title';
  title.textContent = entry.name;

  const statuses = document.createElement('div');
  statuses.className = 'unmatched-row__statuses';

  const statusMessage = document.createElement('p');
  statusMessage.className = 'helper-text unmatched-row__message';
  statusMessage.hidden = true;

  const refreshStatuses = () => {
    statuses.innerHTML = '';
    const tmdbPill = statusPill(
      isTmdbMissing(entry) ? 'Missing TMDb match' : 'TMDb linked',
      isTmdbMissing(entry) ? 'error' : 'success'
    );
    statuses.appendChild(tmdbPill);

    const plexPill = statusPill(
      isPlexMissing(entry) ? 'Missing Plex match' : 'Plex linked',
      isPlexMissing(entry) ? 'error' : 'success'
    );
    statuses.appendChild(plexPill);

    const isResolved = !isTmdbMissing(entry) && !isPlexMissing(entry);
    if (isResolved && typeof onResolved === 'function') {
      onResolved();
    }
  };

  header.append(title, statuses);

  const fields = document.createElement('div');
  fields.className = 'unmatched-row__fields';

  let tmdbInput;
  if (isServiceEnabled('tmdbEnabled')) {
    const tmdbField = document.createElement('label');
    tmdbField.className = 'unmatched-row__field';

    const tmdbLabel = document.createElement('span');
    tmdbLabel.className = 'unmatched-row__label';
    tmdbLabel.textContent = 'TMDb ID';

    tmdbInput = document.createElement('input');
    tmdbInput.type = 'text';
    tmdbInput.inputMode = 'numeric';
    tmdbInput.placeholder = 'e.g. 1399';
    tmdbInput.value = entry.config?.tmdb_id ?? '';

    tmdbInput.addEventListener('input', () => {
      const result = applyTmdbValue(entry, tmdbInput.value);
      statusMessage.hidden = true;
      tmdbInput.classList.remove('input-error');
      if (!result.valid) {
        statusMessage.textContent = result.message;
        statusMessage.hidden = false;
        tmdbInput.classList.add('input-error');
      }
      refreshStatuses();
    });

    tmdbField.append(tmdbLabel, tmdbInput);
    fields.appendChild(tmdbField);
  }

  let librarySelect;
  let ratingInput;
  if (isServiceEnabled('plexEnabled')) {
    const libraryField = document.createElement('label');
    libraryField.className = 'unmatched-row__field';

    const libraryLabel = document.createElement('span');
    libraryLabel.className = 'unmatched-row__label';
    libraryLabel.textContent = 'Plex library';

    librarySelect = document.createElement('select');
    librarySelect.innerHTML = '<option value="">Select library</option>';

    Object.keys(state.libraries || {}).forEach((library) => {
      const option = document.createElement('option');
      option.value = library;
      option.textContent = library;
      librarySelect.appendChild(option);
    });

    librarySelect.value = entry.config?.library || '';
    librarySelect.addEventListener('change', () => {
      applyLibraryValue(entry, librarySelect.value);
      refreshStatuses();
    });

    libraryField.append(libraryLabel, librarySelect);
    fields.appendChild(libraryField);

    const ratingField = document.createElement('label');
    ratingField.className = 'unmatched-row__field';

    const ratingLabel = document.createElement('span');
    ratingLabel.className = 'unmatched-row__label';
    ratingLabel.textContent = 'Plex rating key';

    ratingInput = document.createElement('input');
    ratingInput.type = 'text';
    ratingInput.placeholder = 'e.g. 12345';
    ratingInput.value = entry.config?.rating_key ?? '';

    ratingInput.addEventListener('input', () => {
      applyRatingKeyValue(entry, ratingInput.value);
      refreshStatuses();
    });

    ratingField.append(ratingLabel, ratingInput);
    fields.appendChild(ratingField);
  }

  const applySearchResult = (result) => {
    const { ids = {} } = result || {};

    if (result?.library && librarySelect) {
      librarySelect.value = result.library;
      applyLibraryValue(entry, result.library);
    }

    if (ids.tmdb_id && tmdbInput) {
      tmdbInput.value = ids.tmdb_id;
      applyTmdbValue(entry, tmdbInput.value);
      statusMessage.hidden = true;
      tmdbInput.classList.remove('input-error');
    }

    if (result?.rating_key && ratingInput) {
      ratingInput.value = result.rating_key;
      applyRatingKeyValue(entry, ratingInput.value);
    }

    if (ids.tvdb_id) {
      const tvdb = Number.parseInt(ids.tvdb_id, 10);
      entry.config.tvdb_id = Number.isNaN(tvdb) ? ids.tvdb_id : tvdb;
    }

    if (ids.imdb_id) {
      entry.config.imdb_id = ids.imdb_id;
    }

    refreshStatuses();
  };

  let searchSection = null;
  if (isServiceEnabled('plexEnabled')) {
    searchSection = document.createElement('div');
    searchSection.className = 'unmatched-row__search';

    const searchControls = document.createElement('div');
    searchControls.className = 'unmatched-row__search-controls';

    const searchInput = document.createElement('input');
    searchInput.type = 'search';
    searchInput.placeholder = 'Search Plex...';
    searchInput.value = entry.name;

    const searchButton = document.createElement('button');
    searchButton.type = 'button';
    searchButton.textContent = 'Search Plex';

    const resultsContainer = document.createElement('div');
    resultsContainer.className = 'search-results unmatched-row__search-results';

    searchControls.append(searchInput, searchButton);
    searchSection.append(searchControls, resultsContainer);

    const highlightSelection = (element) => {
      resultsContainer.querySelectorAll('.search-result').forEach((item) => {
        item.classList.remove('active');
      });
      element.classList.add('active');
    };

    const renderSearchResults = (results) => {
      resultsContainer.innerHTML = '';

      if (!results.length) {
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
        }</p><p class="helper-text">${result.summary || ''}</p>`;

        const select = document.createElement('button');
        select.textContent = 'Use match';
        select.addEventListener('click', () => {
          applySearchResult(result);
          highlightSelection(item);
        });

        item.append(summary, select);
        resultsContainer.appendChild(item);
      });
    };

    const performSearch = async () => {
      const query = searchInput.value.trim();
      if (!query) {
        resultsContainer.textContent = 'Enter a search term to find matches.';
        return;
      }

      resultsContainer.innerHTML = '<p class="helper-text">Searching…</p>';

      try {
        const response = await fetch(`/api/plex/search?q=${encodeURIComponent(query)}`);
        if (!response.ok) {
          throw new Error('Search failed');
        }
        const data = await response.json();
        renderSearchResults(data.results || []);
      } catch (error) {
        resultsContainer.innerHTML = '';
        resultsContainer.textContent = error.message || 'Search failed';
      }
    };

    searchButton.addEventListener('click', performSearch);
    searchInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        performSearch();
      }
    });
  }

  const actions = document.createElement('div');
  actions.className = 'unmatched-row__actions';

  const editButton = document.createElement('button');
  editButton.type = 'button';
  editButton.textContent = 'Edit in list';
  editButton.addEventListener('click', () => {
    setEntryCollapsed(entry.id, false);
    state.pendingEntryId = entry.id;
    renderEntries();
    const target = document.querySelector(`[data-entry-id="${entry.id}"]`);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  });

  actions.appendChild(editButton);

  const rowChildren = [header, fields];
  if (searchSection) {
    rowChildren.push(searchSection);
  }
  rowChildren.push(statusMessage, actions);

  row.append(...rowChildren);

  refreshStatuses();

  return row;
}

function openUnmatchedItemsModal() {
  const modal = buildModal('Unmatched metadata');
  addFloatingCloseButton(modal, 'Close unmatched metadata dialog');

  const intro = document.createElement('div');
  intro.className = 'modal-section modal-section--muted';
  const introText = document.createElement('p');
  introText.className = 'helper-text';
  introText.textContent =
    'These series could not be linked to TMDb or Plex. Provide IDs here or jump to the entry to make further edits.';
  intro.appendChild(introText);

  const list = document.createElement('div');
  list.className = 'unmatched-list';

  const renderList = () => {
    list.innerHTML = '';
    const unmatched = findUnmatchedEntries();

    if (!unmatched.length) {
      const resolved = document.createElement('p');
      resolved.className = 'helper-text';
      resolved.textContent = 'All series are linked to TMDb and Plex.';
      list.appendChild(resolved);
      return;
    }

    unmatched.forEach(({ entry }) => {
      list.appendChild(buildUnmatchedRow(entry, renderList));
    });
  };

  renderList();

  modal.content.append(intro, list);

  const saveButton = document.createElement('button');
  saveButton.type = 'button';
  saveButton.textContent = 'Save changes';
  saveButton.addEventListener('click', async () => {
    saveButton.disabled = true;
    await saveConfiguration();
    saveButton.disabled = false;
  });

  modal.footer.append(
    saveButton,
    closeButton(() => {
      closeModal(modal.element);
    })
  );
}

function formatActivityTimestamp(timestamp) {
  if (!timestamp) {
    return 'Time unavailable';
  }

  const numeric = Number(timestamp);
  if (!Number.isFinite(numeric)) {
    return 'Time unavailable';
  }

  const millis = numeric < 1e12 ? numeric * 1000 : numeric;
  const date = new Date(millis);
  if (Number.isNaN(date.getTime())) {
    return 'Time unavailable';
  }

  return date.toLocaleString();
}

function renderActivityList(listElement, entries, emptyMessage, timestampLabel) {
  listElement.innerHTML = '';

  if (!entries || entries.length === 0) {
    const empty = document.createElement('li');
    empty.className = 'modal-activity-empty';
    empty.textContent = emptyMessage;
    listElement.appendChild(empty);
    return;
  }

  entries.forEach((entry) => {
    const item = document.createElement('li');
    item.className = 'modal-activity-item';

    const series = document.createElement('div');
    series.className = 'modal-activity-item__series';
    series.textContent = entry.series || 'Unknown series';

    const episode = document.createElement('div');
    episode.className = 'modal-activity-item__episode';
    episode.textContent = entry.episode || 'Episode title unavailable';

    const meta = document.createElement('div');
    meta.className = 'modal-activity-item__meta';
    const metaParts = [];
    if (entry.season) {
      metaParts.push(entry.season);
    }
    if (entry.timestamp) {
      metaParts.push(`${timestampLabel} ${formatActivityTimestamp(entry.timestamp)}`);
    }
    meta.textContent = metaParts.join(' • ');

    item.append(series, episode, meta);
    listElement.appendChild(item);
  });
}

async function fetchRecentActivity() {
  const response = await fetch('/api/tautulli/recents');
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.error || 'Unable to load recent activity');
  }

  return data;
}

function openRecentsModal() {
  const modal = buildModal('Recents');
  addFloatingCloseButton(modal, 'Close recents dialog');

  const intro = document.createElement('div');
  intro.className = 'modal-section modal-section--muted';
  intro.innerHTML = '<p class="helper-text">Recent Tautulli activity is filtered to shows configured in tv.yml.</p>';

  const status = document.createElement('p');
  status.className = 'helper-text';
  status.textContent = 'Loading recent activity...';

  const grid = document.createElement('div');
  grid.className = 'modal-activity-grid';

  const watchedSection = document.createElement('div');
  watchedSection.className = 'modal-section';
  const watchedHeader = document.createElement('h3');
  watchedHeader.textContent = 'Recently watched';
  const watchedList = document.createElement('ul');
  watchedList.className = 'modal-activity-list';
  watchedSection.append(watchedHeader, watchedList);

  const addedSection = document.createElement('div');
  addedSection.className = 'modal-section';
  const addedHeader = document.createElement('h3');
  addedHeader.textContent = 'Recently added';
  const addedList = document.createElement('ul');
  addedList.className = 'modal-activity-list';
  addedSection.append(addedHeader, addedList);

  grid.append(watchedSection, addedSection);

  const settingsButton = document.createElement('button');
  settingsButton.type = 'button';
  settingsButton.textContent = 'Update Tautulli settings';
  settingsButton.addEventListener('click', () => {
    closeModal(modal.element);
    openSettingsModal();
  });

  const refreshButton = document.createElement('button');
  refreshButton.type = 'button';
  refreshButton.textContent = 'Refresh';

  const refreshActivity = async () => {
    status.textContent = 'Loading recent activity...';
    refreshButton.disabled = true;
    settingsButton.disabled = true;

    try {
      const data = await fetchRecentActivity();
      renderActivityList(watchedList, data.watched || [], 'No watched episodes in the last 7 days.', 'Watched');
      renderActivityList(addedList, data.added || [], 'No episodes added in the last 7 days.', 'Added');
      if (data.generatedAt) {
        status.textContent = `Updated ${formatActivityTimestamp(data.generatedAt)}`;
      } else {
        status.textContent = 'Activity loaded';
      }
    } catch (error) {
      status.textContent = error.message;
    } finally {
      refreshButton.disabled = false;
      settingsButton.disabled = false;
    }
  };

  refreshActivity();

  modal.content.append(intro, status, grid);
  modal.footer.append(refreshButton, settingsButton, closeButton(() => closeModal(modal.element)));
}

function formatSettingLabel(key) {
  if (!key) return '';
  return key
    .toString()
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function openSettingsModal() {
  const modal = buildModal('Settings');
  addFloatingCloseButton(modal, 'Close settings dialog');

  const tautulli = state.settings?.tautulli || {};
  const seriesSyncInterval = Number(state.settings?.series_sync_interval_seconds);
  const preferences = state.settings?.preferences || {};

  const tautulliSection = document.createElement('div');
  tautulliSection.className = 'modal-section';

  const tautulliHeader = document.createElement('div');
  tautulliHeader.className = 'modal-section__header';
  const tautulliTitle = document.createElement('h3');
  tautulliTitle.textContent = 'Tautulli connection';
  const intro = document.createElement('p');
  intro.className = 'helper-text';
  intro.textContent = 'Provide your Tautulli address and API key to enable Recents.';
  tautulliHeader.append(tautulliTitle, intro);

  const tautulliControls = document.createElement('div');
  tautulliControls.className = 'modal-controls';

  const urlField = document.createElement('label');
  urlField.className = 'modal-controls__field';
  const urlLabel = document.createElement('span');
  urlLabel.className = 'modal-controls__label';
  urlLabel.textContent = 'Tautulli URL';
  const urlInput = document.createElement('input');
  urlInput.type = 'url';
  urlInput.value = tautulli.url || '';
  urlInput.placeholder = 'http://localhost:8181';
  urlField.append(urlLabel, urlInput);

  const keyField = document.createElement('label');
  keyField.className = 'modal-controls__field';
  const keyLabel = document.createElement('span');
  keyLabel.className = 'modal-controls__label';
  keyLabel.textContent = 'API key';
  const keyInput = document.createElement('input');
  keyInput.type = 'text';
  keyInput.value = tautulli.api_key || '';
  keyInput.autocomplete = 'off';
  keyField.append(keyLabel, keyInput);

  const userField = document.createElement('label');
  userField.className = 'modal-controls__field';
  const userLabel = document.createElement('span');
  userLabel.className = 'modal-controls__label';
  userLabel.textContent = 'Plex user';
  const userSelect = document.createElement('select');
  userSelect.className = 'modal-select';
  const defaultUserOption = document.createElement('option');
  defaultUserOption.value = '';
  defaultUserOption.textContent = 'All users';
  userSelect.append(defaultUserOption);
  userField.append(userLabel, userSelect);

  const userStatus = document.createElement('p');
  userStatus.className = 'helper-text modal-controls__status';
  userStatus.textContent = 'Loading users...';

  const verifyField = document.createElement('label');
  verifyField.className = 'modal-controls__field';
  const verifyLabel = document.createElement('span');
  verifyLabel.className = 'modal-controls__label';
  verifyLabel.textContent = 'Verify SSL certificates';
  const verifyInput = document.createElement('input');
  verifyInput.type = 'checkbox';
  verifyInput.checked = tautulli.verify_ssl !== false;
  verifyField.append(verifyLabel, verifyInput);

  const syncSection = document.createElement('div');
  syncSection.className = 'modal-section';
  const syncHeader = document.createElement('div');
  syncHeader.className = 'modal-section__header';
  const syncTitle = document.createElement('h3');
  syncTitle.textContent = 'Series sync';
  const syncIntro = document.createElement('p');
  syncIntro.className = 'helper-text';
  syncIntro.textContent = 'Control how often series files are synced when generating previews.';
  syncHeader.append(syncTitle, syncIntro);

  const syncControls = document.createElement('div');
  syncControls.className = 'modal-controls';

  const syncField = document.createElement('label');
  syncField.className = 'modal-controls__field';
  const syncLabel = document.createElement('span');
  syncLabel.className = 'modal-controls__label';
  syncLabel.textContent = 'Sync interval (seconds)';
  const syncInput = document.createElement('input');
  syncInput.type = 'number';
  syncInput.min = '0';
  syncInput.step = '1';
  syncInput.inputMode = 'numeric';
  syncInput.value = Number.isFinite(seriesSyncInterval)
    ? Math.max(0, seriesSyncInterval)
    : 45;
  syncField.append(syncLabel, syncInput);
  syncControls.append(syncField);
  syncSection.append(syncHeader, syncControls);

  const preferencesSection = document.createElement('div');
  preferencesSection.className = 'modal-section';
  const preferencesHeader = document.createElement('div');
  preferencesHeader.className = 'modal-section__header';
  const preferencesTitle = document.createElement('h3');
  preferencesTitle.textContent = 'Preferences';
  const preferencesIntro = document.createElement('p');
  preferencesIntro.className = 'helper-text';
  preferencesIntro.textContent = 'Edit values from your preferences.yml file.';
  preferencesHeader.append(preferencesTitle, preferencesIntro);

  const preferenceInputs = new Map();

  const renderPreferenceFields = (container, data, path = []) => {
    if (!data || typeof data !== 'object') {
      return;
    }

    Object.entries(data).forEach(([key, value]) => {
      const fieldPath = [...path, key];
      const fieldId = fieldPath.join('.');
      const isNestedObject = value && typeof value === 'object' && !Array.isArray(value);

      if (isNestedObject) {
        const group = document.createElement('div');
        group.className = 'modal-section__group';
        const heading = document.createElement('h4');
        heading.textContent = formatSettingLabel(key);
        group.appendChild(heading);
        renderPreferenceFields(group, value, fieldPath);
        container.appendChild(group);
        return;
      }

      const field = document.createElement('label');
      field.className = 'modal-controls__field';
      const label = document.createElement('span');
      label.className = 'modal-controls__label';
      label.textContent = formatSettingLabel(key);

      const input = document.createElement('input');
      let fieldType = 'string';
      if (typeof value === 'boolean') {
        input.type = 'checkbox';
        input.checked = value;
        fieldType = 'boolean';
      } else if (typeof value === 'number') {
        input.type = 'number';
        input.value = Number.isFinite(value) ? value : '';
        fieldType = 'number';
      } else if (Array.isArray(value)) {
        input.type = 'text';
        input.value = value.join(', ');
        fieldType = 'array';
      } else {
        input.type = 'text';
        input.value = value ?? '';
      }

      preferenceInputs.set(fieldId, { input, type: fieldType });

      field.append(label, input);
      container.appendChild(field);
    });
  };

  const preferencesKeys = Object.keys(preferences || {});
  if (preferencesKeys.length) {
    preferencesKeys.forEach((key) => {
      const section = document.createElement('div');
      section.className = 'modal-section__group';
      const heading = document.createElement('h4');
      heading.textContent = formatSettingLabel(key);
      section.appendChild(heading);
      renderPreferenceFields(section, preferences[key], [key]);
      preferencesSection.appendChild(section);
    });
  } else {
    const emptyMessage = document.createElement('p');
    emptyMessage.className = 'helper-text';
    emptyMessage.textContent = 'No preferences found. Ensure preferences.yml is available to edit settings here.';
    preferencesSection.appendChild(emptyMessage);
  }

  const status = document.createElement('p');
  status.className = 'helper-text';
  status.textContent = '';

  const buildPreferencePayload = (template, path = []) => {
    if (template && typeof template === 'object' && !Array.isArray(template)) {
      const result = {};
      Object.entries(template).forEach(([key, value]) => {
        result[key] = buildPreferencePayload(value, [...path, key]);
      });
      return result;
    }

    const fieldId = path.join('.');
    const meta = preferenceInputs.get(fieldId);
    if (!meta) {
      return template;
    }

    if (meta.type === 'boolean') {
      return meta.input.checked;
    }
    if (meta.type === 'number') {
      const parsed = Number(meta.input.value);
      return Number.isNaN(parsed) ? template : parsed;
    }
    if (meta.type === 'array') {
      return meta.input.value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean);
    }

    return meta.input.value;
  };

  const saveButton = document.createElement('button');
  saveButton.type = 'button';
  saveButton.textContent = 'Save settings';
  saveButton.addEventListener('click', async () => {
    saveButton.disabled = true;
    status.textContent = 'Saving settings...';
    const parsedSyncInterval = Number(syncInput.value);
    const syncIntervalSeconds = Number.isFinite(parsedSyncInterval)
      ? Math.max(0, parsedSyncInterval)
      : 45;
    try {
      await saveSettings({
        series_sync_interval_seconds: syncIntervalSeconds,
        tautulli: {
          url: urlInput.value,
          api_key: keyInput.value,
          user_id: userSelect.value,
          verify_ssl: verifyInput.checked,
        },
        preferences: buildPreferencePayload(preferences),
      });
      status.textContent = 'Settings saved.';
      showToast('Settings updated');
    } catch (error) {
      status.textContent = error.message;
      showToast(error.message, 'error');
    } finally {
      saveButton.disabled = false;
    }
  });

  const loadUsers = async () => {
    userSelect.disabled = true;
    userStatus.textContent = 'Loading users...';
    try {
      const response = await fetch('/api/tautulli/users');
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || 'Unable to load users');
      }

      const users = Array.isArray(data.users) ? data.users : [];
      while (userSelect.options.length > 1) {
        userSelect.remove(1);
      }

      users.forEach((user) => {
        if (!user || !user.id) {
          return;
        }
        const option = document.createElement('option');
        option.value = user.id;
        option.textContent = user.name || user.id;
        userSelect.append(option);
      });

      userSelect.value = tautulli.user_id || '';
      userStatus.textContent = users.length
        ? 'Select a Plex user to filter watch history.'
        : 'No users returned from Tautulli.';
    } catch (error) {
      userStatus.textContent = error.message;
    } finally {
      userSelect.disabled = false;
    }
  };

  loadUsers();

  tautulliControls.append(urlField, keyField, userField, verifyField);
  tautulliSection.append(tautulliHeader, tautulliControls, userStatus);
  preferencesSection.prepend(preferencesHeader);

  modal.content.append(tautulliSection, syncSection, preferencesSection, status);
  modal.footer.append(saveButton, closeButton(() => closeModal(modal.element)));
}

// -----------------------------------------------------------------------------
// Add entry modal
// -----------------------------------------------------------------------------
function openAddEntryModal() {
  const modal = buildModal('Add series entry');
  addFloatingCloseButton(modal, 'Close add series dialog');

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
    initializeEntryPreviewState(newEntry);
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
  return {
    name: entry.name,
    config: cloneData(entry.config),
    previewEpisode: entry.previewEpisode || 'random',
  };
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

let cacheDbPromise = null;
let cacheDbUnavailable = false;

function loadLegacyPreviewCache() {
  try {
    const cached = localStorage.getItem(PREVIEW_CACHE_STORAGE_KEY);
    return cached ? JSON.parse(cached) : {};
  } catch (error) {
    console.warn('Failed to load legacy preview cache', error);
    return {};
  }
}

function persistLegacyPreviewCache() {
  try {
    localStorage.setItem(
      PREVIEW_CACHE_STORAGE_KEY,
      JSON.stringify(state.previewCache)
    );
  } catch (error) {
    console.warn('Failed to persist legacy preview cache', error);
  }
}

function openCacheDb() {
  if (cacheDbUnavailable || typeof indexedDB === 'undefined') {
    cacheDbUnavailable = true;
    return Promise.resolve(null);
  }

  if (cacheDbPromise) {
    return cacheDbPromise;
  }

  cacheDbPromise = new Promise((resolve) => {
    const request = indexedDB.open(CACHE_DB_NAME, CACHE_DB_VERSION);

    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(PREVIEW_DB_STORE)) {
        db.createObjectStore(PREVIEW_DB_STORE, { keyPath: 'key' });
      }
      if (!db.objectStoreNames.contains(LOGO_DB_STORE)) {
        db.createObjectStore(LOGO_DB_STORE, { keyPath: 'key' });
      }
    };

    request.onsuccess = () => {
      resolve(request.result);
    };

    request.onerror = () => {
      console.warn('Failed to open cache database', request.error);
      cacheDbUnavailable = true;
      resolve(null);
    };

    request.onblocked = () => {
      console.warn('Cache database open request is blocked');
    };
  });

  return cacheDbPromise;
}

async function runCacheDbRequest(storeName, mode, executor) {
  const db = await openCacheDb();
  if (!db) {
    return null;
  }

  return new Promise((resolve, reject) => {
    try {
      const transaction = db.transaction(storeName, mode);
      const store = transaction.objectStore(storeName);
      const request = executor(store);

      transaction.oncomplete = () => resolve(request?.result ?? null);
      transaction.onabort = () => reject(transaction.error || request?.error);
      transaction.onerror = () => reject(transaction.error || request?.error);
    } catch (error) {
      reject(error);
    }
  });
}

async function readAllPreviewCacheEntries() {
  try {
    const entries = await runCacheDbRequest(PREVIEW_DB_STORE, 'readonly', (store) =>
      store.getAll()
    );
    return Array.isArray(entries) ? entries : [];
  } catch (error) {
    console.warn('Failed to load previews from IndexedDB', error);
    return [];
  }
}

async function readPreviewCacheEntry(key) {
  if (!key) {
    return null;
  }

  if (state.previewCache[key]) {
    return state.previewCache[key];
  }

  try {
    const entry = await runCacheDbRequest(PREVIEW_DB_STORE, 'readonly', (store) =>
      store.get(key)
    );
    if (entry) {
      state.previewCache[key] = entry;
    }
    return entry || null;
  } catch (error) {
    console.warn('Failed to read preview cache entry', error);
    return null;
  }
}

async function writePreviewCacheEntry(key, value) {
  if (!key || !value) {
    return false;
  }
  try {
    await runCacheDbRequest(PREVIEW_DB_STORE, 'readwrite', (store) =>
      store.put({ ...value, key })
    );
    return true;
  } catch (error) {
    console.warn('Failed to persist preview cache to IndexedDB', error);
    return false;
  }
}

async function deletePreviewCacheEntry(key) {
  if (!key) {
    return;
  }
  try {
    await runCacheDbRequest(PREVIEW_DB_STORE, 'readwrite', (store) =>
      store.delete(key)
    );
  } catch (error) {
    console.warn('Failed to delete preview cache entry', error);
  }
}

async function loadPreviewCache() {
  state.previewCache = {};

  const dbEntries = await readAllPreviewCacheEntries();
  dbEntries.forEach((entry) => {
    if (entry?.key && entry.src) {
      state.previewCache[entry.key] = { snapshot: entry.snapshot, src: entry.src };
    }
  });

  const legacyCache = loadLegacyPreviewCache();
  const migrationTasks = [];
  Object.entries(legacyCache).forEach(([key, value]) => {
    if (!value) {
      return;
    }

    if (!state.previewCache[key]) {
      state.previewCache[key] = value;
    }

    migrationTasks.push(writePreviewCacheEntry(key, value));
  });

  if (migrationTasks.length) {
    await Promise.allSettled(migrationTasks);
  }

  // Keep the legacy cache in sync for fallback if IndexedDB is unavailable.
  persistLegacyPreviewCache();
}

async function readAllLogoCacheEntries() {
  try {
    const entries = await runCacheDbRequest(LOGO_DB_STORE, 'readonly', (store) =>
      store.getAll()
    );
    return Array.isArray(entries) ? entries : [];
  } catch (error) {
    console.warn('Failed to load logos from IndexedDB', error);
    return [];
  }
}

async function readLogoCacheEntry(key) {
  if (!key) {
    return null;
  }

  if (state.logoCache[key]) {
    return state.logoCache[key];
  }

  try {
    const entry = await runCacheDbRequest(LOGO_DB_STORE, 'readonly', (store) =>
      store.get(key)
    );
    if (entry) {
      state.logoCache[key] = entry;
    }
    return entry || null;
  } catch (error) {
    console.warn('Failed to read logo cache entry', error);
    return null;
  }
}

async function writeLogoCacheEntry(key, value) {
  if (!key || !value) {
    return false;
  }
  try {
    await runCacheDbRequest(LOGO_DB_STORE, 'readwrite', (store) =>
      store.put({ ...value, key })
    );
    return true;
  } catch (error) {
    console.warn('Failed to persist logo cache to IndexedDB', error);
    return false;
  }
}

async function deleteLogoCacheEntry(key) {
  if (!key) {
    return;
  }
  try {
    await runCacheDbRequest(LOGO_DB_STORE, 'readwrite', (store) =>
      store.delete(key)
    );
  } catch (error) {
    console.warn('Failed to delete logo cache entry', error);
  }
}

async function loadLogoCache() {
  state.logoCache = {};

  const dbEntries = await readAllLogoCacheEntries();
  dbEntries.forEach((entry) => {
    if (entry?.key && entry.src) {
      state.logoCache[entry.key] = { snapshot: entry.snapshot, src: entry.src };
    }
  });
}

function logoCacheKey(entry, snapshot = null) {
  const name = typeof entry === 'string' ? entry : entry?.name;
  if (!name) {
    return null;
  }
  const resolvedSnapshot = snapshot || (typeof entry === 'object' ? entry.logoSnapshot : null);
  return resolvedSnapshot ? `${name}:${hashString(resolvedSnapshot)}` : name;
}

function getImageDataUrl(image) {
  if (
    !image ||
    !image.complete ||
    image.naturalWidth === 0 ||
    image.naturalHeight === 0
  ) {
    return null;
  }

  if (typeof image.src === 'string' && image.src.startsWith('data:')) {
    return image.src;
  }

  const canvas = document.createElement('canvas');
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const context = canvas.getContext('2d');
  if (!context) {
    return null;
  }

  try {
    context.drawImage(image, 0, 0);
    return canvas.toDataURL();
  } catch (error) {
    console.warn('Failed to serialize logo image', error);
    return null;
  }
}

async function restoreCachedLogo(entry) {
  if (!entry?.name) {
    return;
  }

  const snapshot = JSON.stringify(snapshotEntry(entry));
  const cached =
    (await readLogoCacheEntry(logoCacheKey(entry, snapshot))) ||
    (await readLogoCacheEntry(logoCacheKey(entry)));

  if (cached?.src) {
    entry.logoSrc = cached.src;
    entry.logoSnapshot = cached.snapshot || null;
  }
}

async function updateLogoCache(entry, src, snapshotOverride = null) {
  if (!entry?.name || !src) {
    return;
  }

  const snapshot = snapshotOverride || JSON.stringify(snapshotEntry(entry));
  const key = logoCacheKey(entry, snapshot);
  if (!key) {
    return;
  }

  const value = { snapshot, src };
  const existing = state.logoCache[key];
  if (existing?.src === value.src && existing?.snapshot === value.snapshot) {
    entry.logoSrc = value.src;
    entry.logoSnapshot = value.snapshot;
    return;
  }
  state.logoCache[key] = value;
  entry.logoSrc = src;
  entry.logoSnapshot = snapshot;
  await writeLogoCacheEntry(key, value);
}

async function updateLogoCacheFromElement(entry, image) {
  const src = getImageDataUrl(image);
  if (!src) {
    return;
  }
  await updateLogoCache(entry, src);
}

async function clearLogoCacheEntry(entry) {
  const keys = [logoCacheKey(entry, entry?.logoSnapshot), logoCacheKey(entry)];
  const uniqueKeys = [...new Set(keys.filter(Boolean))];

  uniqueKeys.forEach((key) => {
    if (state.logoCache[key]) {
      delete state.logoCache[key];
    }
  });

  entry.logoSrc = null;
  entry.logoSnapshot = null;

  await Promise.all(uniqueKeys.map((key) => deleteLogoCacheEntry(key)));
}

function previewCacheKey(entry) {
  if (!entry?.name) {
    return null;
  }
  const snapshot = JSON.stringify(snapshotEntry(entry));
  return `${entry.name}:${hashString(snapshot)}`;
}

function legacyPreviewCacheKey(entry) {
  return entry?.name || null;
}

function hashString(value) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return hash.toString(16);
}

async function restoreCachedPreview(entry) {
  const key = previewCacheKey(entry);
  const legacyKey = legacyPreviewCacheKey(entry);
  if (!key && !legacyKey) {
    return;
  }

  const snapshot = JSON.stringify(snapshotEntry(entry));
  const cached = (await readPreviewCacheEntry(key)) || null;
  const legacy = (await readPreviewCacheEntry(legacyKey)) || null;
  const match = cached || legacy;
  if (match?.src) {
    entry.previewSrc = match.src;
    entry.previewStale = match.snapshot !== snapshot;
  }
}

async function updatePreviewCache(entry) {
  const key = previewCacheKey(entry);
  if (!key || !entry.previewSrc) {
    return;
  }
  const value = {
    snapshot: JSON.stringify(snapshotEntry(entry)),
    src: entry.previewSrc,
  };
  state.previewCache[key] = value;
  entry.previewStale = false;
  await writePreviewCacheEntry(key, value);
  persistLegacyPreviewCache();
}

async function clearPreviewCacheEntry(entry) {
  const key = previewCacheKey(entry);
  const legacyKey = legacyPreviewCacheKey(entry);
  if (key && state.previewCache[key]) {
    delete state.previewCache[key];
  }
  if (legacyKey && state.previewCache[legacyKey]) {
    delete state.previewCache[legacyKey];
  }

  const deletions = [deletePreviewCacheEntry(key)];
  if (legacyKey && legacyKey !== key) {
    deletions.push(deletePreviewCacheEntry(legacyKey));
  }

  await Promise.all(deletions);

  persistLegacyPreviewCache();
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

    await Promise.all(
      changedEntries.map(async (entry) => {
        await invalidateEntryPreview(entry);
        recordEntrySaveSnapshot(entry);
      })
    );
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

