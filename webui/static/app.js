const state = {
  libraries: {},
  entries: [],
  fields: [],
  fontDirectory: '/config/fonts',
  filter: '',
  pendingEntryId: null,
  collapsedEntries: new Set(),
  persistedBaselineFingerprint: null,
  persistedServerFingerprint: null,
  persistedBaselinePayload: null,
  persistedBaselineEntryOrder: [],
  isDirty: false,
  logoCache: {},
  cardTypeExtras: {},
  logoBackgrounds: new Map(),
  services: {
    tmdbEnabled: true,
    plexEnabled: true,
  },
  settings: {
    series_sync_interval_seconds: 45,
    entry_visibility_default_mode: 'basic',
    preference_setup_required: false,
    preference_file_generated: false,
    preferences: {},
    tautulli: {
      url: '',
      api_key: '',
      verify_ssl: true,
    },
  },
  validationIssues: new Map(),
};

let saveInProgress = false;
let saveStatusPanel = null;
let saveStatusArchive = [];
let persistedFingerprintPollTimer = null;
let persistedFingerprintPollInFlight = false;

const VALIDATION_SEVERITY_ERROR = 'error';
const VALIDATION_SEVERITY_WARNING = 'warning';

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
  dirtyIndicator: document.getElementById('dirty-indicator'),
  plexStatusLight: document.getElementById('plex-status-light'),
  tautulliStatusLight: document.getElementById('tautulli-status-light'),
  unmatchedIssues: document.getElementById('unmatched-issues'),
  recents: document.getElementById('open-recents'),
  settings: document.getElementById('open-settings'),
  onboarding: document.getElementById('onboarding-layer'),
  modals: document.getElementById('modals'),
  optionInfoTemplate: document.getElementById('option-info-template'),
};

const toastContainer = document.createElement('div');
toastContainer.className = 'toast-container';
document.body.appendChild(toastContainer);

const CLIENT_LOG_ENDPOINT = '/api/client-log';
const LOGO_BACKGROUND_STORAGE_KEY = 'tcm-logo-backgrounds';
const CACHE_DB_NAME = 'tcm-cache';
const CACHE_DB_VERSION = 2;
const CACHE_DB_OPEN_TIMEOUT_MS = 2000;
const PREVIEW_CACHE_MAX_AGE_MS = 1000 * 60 * 60 * 12;
const LOGO_DB_STORE = 'logos';
const DEFAULT_BACKUP_DIRECTORY = '/config/backups';
const FONT_EXTENSIONS = ['.ttf', '.otf', '.woff', '.woff2', '.ttc'];
const DESTRUCTIVE_ACTION_UNDO_WINDOW_MS = 9000;
const PERSISTED_FINGERPRINT_POLL_INTERVAL_MS = 5000;
const HELP_LINKS = {
  gettingStarted: 'https://github.com/CollinHeist/TitleCardMaker#readme',
  readmeUsage: 'https://github.com/CollinHeist/TitleCardMaker#usage',
  readmeRequirements: 'https://github.com/CollinHeist/TitleCardMaker#requirements',
  plexSetup: 'https://github.com/CollinHeist/TitleCardMaker/wiki/Plex',
  tautulliSetup: 'https://github.com/CollinHeist/TitleCardMaker/wiki/Tautulli',
};
const ONBOARDING_STEP_ORDER = [
  'set_preferences',
  'add_first_series',
  'preview_card',
  'save_config',
  'run_build',
];

const ERROR_ASSIST_RULES = [
  {
    signatureAny: ['no such file', 'path', 'directory not found', 'file not found'],
    title: 'Path looks invalid',
    steps: [
      'Fix typos and remove extra spaces from the path.',
      'Confirm the file/folder is mounted and readable.',
      'Save settings, then retry the action.',
    ],
    readmeLink: HELP_LINKS.gettingStarted,
    settingsLabel: 'Open Settings',
    settingsAction: () => openSettingsModal(),
  },
  {
    signatureAny: ['api key', 'unauthorized', 'forbidden', '401', '403'],
    title: 'API credentials were rejected',
    steps: [
      'Copy a fresh API key from your service.',
      'Update the key in Settings → Tautulli connection.',
      'Use Recents to verify the connection.',
    ],
    readmeLink: HELP_LINKS.readmeUsage,
    settingsLabel: 'Tautulli Settings',
    settingsAction: () => openSettingsModal(),
  },
  {
    signatureAny: ['imagemagick', 'library unavailable', 'module not found', 'missing dependency'],
    title: 'A required library is unavailable',
    steps: [
      'Install missing dependencies listed in README.',
      'If Docker is used, update/recreate the container.',
      'Restart TitleCardMaker and rerun.',
    ],
    readmeLink: HELP_LINKS.readmeRequirements,
    settingsLabel: 'Open Preferences',
    settingsAction: () => openPreferenceWizardModal(),
  },
  {
    signatureAny: ['font not found', 'unable to load font', 'font'],
    title: 'Font file could not be resolved',
    steps: [
      'Pick a valid font file in your mounted fonts directory.',
      'Use supported extensions (.ttf/.otf/.woff/.woff2/.ttc).',
      'Save and preview again.',
    ],
    readmeLink: HELP_LINKS.gettingStarted,
    settingsLabel: 'Open Settings',
    settingsAction: () => openSettingsModal(),
  },
];

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

const pendingDestructiveActions = new Map();

function makeValidationIssue(severity, message) {
  return { severity, message };
}

function validationStateKey(entryId, fieldId) {
  return `${entryId || 'global'}::${fieldId || 'unknown'}`;
}

function setValidationIssue(entryId, fieldId, issue) {
  const key = validationStateKey(entryId, fieldId);
  if (!issue) {
    state.validationIssues.delete(key);
  } else {
    state.validationIssues.set(key, issue);
  }
  updateSaveButtonDisabledState();
}

function hasHardValidationErrors() {
  return [...state.validationIssues.values()].some(
    (issue) => issue && issue.severity === VALIDATION_SEVERITY_ERROR
  );
}

function updateSaveButtonDisabledState() {
  if (!dom.save) {
    return;
  }
  dom.save.disabled = saveInProgress || hasHardValidationErrors();
}

function validatePathField(rawValue) {
  const value = String(rawValue ?? '').trim();
  if (!value) {
    return [];
  }
  if (/[\0]/u.test(value)) {
    return [makeValidationIssue(VALIDATION_SEVERITY_ERROR, 'Path cannot include null characters.')];
  }
  if (/\s$/u.test(String(rawValue ?? ''))) {
    return [
      makeValidationIssue(
        VALIDATION_SEVERITY_WARNING,
        'Path has trailing whitespace and may not resolve as expected.'
      ),
    ];
  }
  return [];
}

function validateYearSuffix(name) {
  const value = String(name ?? '').trim();
  if (!value) {
    return [makeValidationIssue(VALIDATION_SEVERITY_ERROR, 'Series name is required.')];
  }
  if (/\(\d+\)\s*$/u.test(value) && !/\((19|20)\d{2}\)\s*$/u.test(value)) {
    return [
      makeValidationIssue(
        VALIDATION_SEVERITY_WARNING,
        'Use a 4-digit year like “Series Name (2024)”.'
      ),
    ];
  }
  return [];
}

function validateIdentifier(fieldId, rawValue) {
  const value = String(rawValue ?? '').trim();
  if (!value) {
    return [];
  }
  if (fieldId === 'imdb_id') {
    return /^tt\d{5,}$/u.test(value)
      ? []
      : [makeValidationIssue(VALIDATION_SEVERITY_ERROR, 'IMDb IDs should look like tt1234567.')];
  }
  if (/^-?\d+$/u.test(value) && Number(value) > 0) {
    return [];
  }
  return [makeValidationIssue(VALIDATION_SEVERITY_ERROR, 'ID must be a positive integer.')];
}

function validateUrlField(rawValue) {
  const value = String(rawValue ?? '').trim();
  if (!value) {
    return [];
  }
  try {
    const parsed = new URL(value);
    if (!/^https?:$/u.test(parsed.protocol)) {
      return [makeValidationIssue(VALIDATION_SEVERITY_WARNING, 'Prefer an http:// or https:// URL.')];
    }
    return [];
  } catch (_error) {
    return [makeValidationIssue(VALIDATION_SEVERITY_ERROR, 'Enter a valid URL.')];
  }
}

function validateRequiredString(rawValue, label) {
  const value = String(rawValue ?? '').trim();
  if (value) {
    return [];
  }
  return [makeValidationIssue(VALIDATION_SEVERITY_ERROR, `${label || 'Value'} is required.`)];
}

function validatorsForField(field) {
  if (!field?.id) {
    return [];
  }
  if (field.id === 'library_override' || field.id === 'font.file') {
    return [validatePathField];
  }
  if (field.id === 'archive_name') {
    return [
      (value) => validateRequiredString(value, 'Archive name'),
      (value) => validatePathField(value),
    ];
  }
  if (field.id.endsWith('_url') || field.id === 'url') {
    return [validateUrlField];
  }
  if (ID_FIELDS.has(field.id)) {
    return [(value) => validateIdentifier(field.id, value)];
  }
  return [];
}

function setInputValidationState(input, messageNode, issues) {
  const [primaryIssue] = issues;
  const hasError = Boolean(primaryIssue && primaryIssue.severity === VALIDATION_SEVERITY_ERROR);
  input.classList.toggle('input-error', hasError);
  messageNode.hidden = !primaryIssue;
  messageNode.classList.toggle(
    'field-validation__message--warning',
    Boolean(primaryIssue && primaryIssue.severity === VALIDATION_SEVERITY_WARNING)
  );
  messageNode.textContent = primaryIssue ? primaryIssue.message : '';
}

function attachFieldValidation({
  input,
  messageNode,
  entry,
  fieldId,
  validators,
  getValue = () => input.value,
}) {
  const runValidation = () => {
    const issues = validators.flatMap((validator) => validator(getValue()) || []);
    setInputValidationState(input, messageNode, issues);
    const blocking = issues.find((issue) => issue.severity === VALIDATION_SEVERITY_ERROR);
    const warning = issues.find((issue) => issue.severity === VALIDATION_SEVERITY_WARNING);
    setValidationIssue(entry?.id, fieldId, blocking || warning || null);
  };

  input.addEventListener('input', runValidation);
  input.addEventListener('blur', runValidation);
  runValidation();
}

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

function normalizeTimestamp(timestamp) {
  if (timestamp === undefined || timestamp === null) {
    return null;
  }

  const numeric = Number(timestamp);
  if (!Number.isFinite(numeric)) {
    return null;
  }

  // Normalize seconds-based epoch values to milliseconds to match Date.now().
  if (numeric < 1_000_000_000_000) {
    return numeric * 1000;
  }

  return numeric;
}

function isPreviewCacheExpired(cachedAt) {
  const normalized = normalizeTimestamp(cachedAt);
  if (!Number.isFinite(normalized)) {
    return true;
  }

  return Date.now() - normalized > PREVIEW_CACHE_MAX_AGE_MS;
}

function loadLegacyPreviewCache(rawCache) {
  if (!rawCache) {
    return null;
  }

  try {
    const parsed = typeof rawCache === 'string' ? JSON.parse(rawCache) : rawCache;
    if (!parsed || typeof parsed !== 'object') {
      return null;
    }

    const cachedAt = parsed.cachedAt ?? parsed.cached_at ?? parsed.updatedAt;
    if (isPreviewCacheExpired(cachedAt)) {
      return null;
    }

    return {
      ...parsed,
      cachedAt: normalizeTimestamp(cachedAt),
    };
  } catch (error) {
    console.warn('Unable to load legacy preview cache', error);
    return null;
  }
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
let modalIdCounter = 0;
const activeModalStack = [];
const MODAL_FOCUSABLE_SELECTOR = [
  'a[href]',
  'area[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'iframe',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]',
].join(', ');

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
    await loadLogoCache();
    loadLogoBackgroundPreferences();
    await loadMetadata();
    await loadSettings();
    await loadConfiguration();
    startPersistedFingerprintPolling();
    if (!isSetupIncomplete()) {
      markOnboardingStepComplete('set_preferences');
    }
    if (state.entries.length > 0) {
      markOnboardingStepComplete('add_first_series');
    }
    registerEvents();
    setSearchVisibility(false);
    renderEntries();
    requestEntryPreviews(state.entries);
    await refreshConnectionStatusLights();
    maybeOpenPreferenceWizard();
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
    state.settings.entry_visibility_default_mode = normalizeEntryVisibilityMode(
      state.settings?.entry_visibility_default_mode
    );
  } catch (error) {
    console.warn('Unable to load settings', error);
  }
}

function updateConnectionStatusLight(element, serviceName, connected) {
  if (!element) {
    return;
  }

  element.classList.remove('service-status-light--connected', 'service-status-light--disconnected');
  const isConnected = connected === true;
  element.classList.add(
    isConnected ? 'service-status-light--connected' : 'service-status-light--disconnected'
  );
  const statusText = isConnected ? 'connected' : 'not connected';
  element.setAttribute('aria-label', `${serviceName} ${statusText}`);
  element.setAttribute('title', `${serviceName} ${statusText}`);
}

async function refreshConnectionStatusLights() {
  try {
    const response = await fetch('/api/services/status');
    if (!response.ok) {
      throw new Error('Unable to load service status');
    }
    const payload = await response.json();
    updateConnectionStatusLight(dom.plexStatusLight, 'Plex', payload?.plex?.connected === true);
    updateConnectionStatusLight(
      dom.tautulliStatusLight,
      'Tautulli',
      payload?.tautulli?.connected === true
    );
  } catch (error) {
    updateConnectionStatusLight(dom.plexStatusLight, 'Plex', false);
    updateConnectionStatusLight(dom.tautulliStatusLight, 'Tautulli', false);
  }
}

function normalizePreviewEpisode(value) {
  if (value === null || value === undefined) {
    return 'random';
  }

  const normalized = `${value}`.trim();
  if (!normalized || normalized.toLowerCase() === 'random') {
    return 'random';
  }

  return normalized;
}

function configuredPreviewEpisode(entry) {
  const config = entry?.config;
  if (!config || typeof config !== 'object') {
    return null;
  }

  const candidates = [config.previewEpisode, config.preview_episode];
  for (const candidate of candidates) {
    if (candidate === undefined || candidate === null) {
      continue;
    }

    if (Array.isArray(candidate)) {
      const first = candidate.find(Boolean);
      if (first !== undefined && first !== null) {
        return normalizePreviewEpisode(first);
      }
      continue;
    }

    return normalizePreviewEpisode(candidate);
  }

  return null;
}

function resolvePreviewEpisode(entry) {
  const configured = configuredPreviewEpisode(entry);
  if (configured !== null && configured !== undefined) {
    return configured;
  }

  if (entry?.previewEpisode !== undefined && entry.previewEpisode !== null) {
    return normalizePreviewEpisode(entry.previewEpisode);
  }

  return 'random';
}

function syncPreviewEpisodeConfig(entry, previewEpisodeOverride = null) {
  if (!entry) {
    return 'random';
  }

  const previewEpisode =
    previewEpisodeOverride === null
      ? resolvePreviewEpisode(entry)
      : normalizePreviewEpisode(previewEpisodeOverride);

  if (!entry.config || typeof entry.config !== 'object') {
    entry.config = {};
  }

  const prefersSnake =
    'preview_episode' in entry.config && !('previewEpisode' in entry.config);

  if (previewEpisode === 'random') {
    delete entry.config.previewEpisode;
    delete entry.config.preview_episode;
  } else if (prefersSnake) {
    entry.config.preview_episode = previewEpisode;
    delete entry.config.previewEpisode;
  } else {
    entry.config.previewEpisode = previewEpisode;
    delete entry.config.preview_episode;
  }

  entry.previewEpisode = previewEpisode;

  return previewEpisode;
}

function initializeEntryPreviewState(entry) {
  if (!entry) {
    return;
  }
  syncPreviewEpisodeConfig(entry);
  entry.previewEpisodeOptions = entry.previewEpisodeOptions || null;
  entry.previewEpisodeStatus = entry.previewEpisodeStatus || 'idle';
  entry.previewEpisodeError = entry.previewEpisodeError || null;
  entry.previewLoading = false;
  entry.previewSrc = entry.previewSrc || null;
  entry.previewError = entry.previewError || null;
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
      plexLookupFailed: entry.plex_lookup_failed === true,
    };
    initializeEntryPreviewState(mapped);
    return mapped;
  });
  sortEntries();
  state.collapsedEntries = new Set(state.entries.map((entry) => entry.id));
  const currentPayload = buildCurrentNormalizedPayload();
  assignPersistedBaseline(currentPayload, data?.fingerprint);
  refreshDirtyState();
  const stalePreviews = [];
  await Promise.all(
    state.entries.map(async (entry) => {
      await restoreCachedLogo(entry);
      stalePreviews.push(entry);
    })
  );
  requestEntryPreviews(stalePreviews);
}

async function fetchPersistedConfigFingerprint() {
  const response = await fetch('/api/config/fingerprint');
  if (!response.ok) {
    throw new Error('Unable to fetch configuration fingerprint');
  }
  const data = await response.json().catch(() => ({}));
  const fingerprint =
    typeof data?.fingerprint === 'string' && data.fingerprint.trim().length > 0
      ? data.fingerprint.trim()
      : null;
  if (!fingerprint) {
    throw new Error('Fingerprint response was missing a valid fingerprint');
  }
  return fingerprint;
}

function stopPersistedFingerprintPolling() {
  if (!persistedFingerprintPollTimer) {
    return;
  }
  clearInterval(persistedFingerprintPollTimer);
  persistedFingerprintPollTimer = null;
}

function startPersistedFingerprintPolling() {
  stopPersistedFingerprintPolling();
  persistedFingerprintPollTimer = setInterval(() => {
    void reconcilePersistedBaselineFingerprint();
  }, PERSISTED_FINGERPRINT_POLL_INTERVAL_MS);
}

async function reconcilePersistedBaselineFingerprint() {
  if (persistedFingerprintPollInFlight || saveInProgress) {
    return;
  }

  persistedFingerprintPollInFlight = true;
  try {
    const fingerprint = await fetchPersistedConfigFingerprint();
    if (!state.persistedServerFingerprint) {
      state.persistedServerFingerprint = fingerprint;
      refreshDirtyState();
      return;
    }

    if (fingerprint !== state.persistedServerFingerprint) {
      state.persistedServerFingerprint = fingerprint;
      const currentPayload = buildCurrentNormalizedPayload();
      const currentFingerprint = baselineFingerprintFromPayload(currentPayload);
      if (currentFingerprint === fingerprint) {
        assignPersistedBaseline(currentPayload, fingerprint);
      }
      refreshDirtyState();
    }
  } catch (error) {
    console.debug('Unable to reconcile persisted fingerprint', error);
  } finally {
    persistedFingerprintPollInFlight = false;
  }
}

async function saveSettings(payload) {
  const response = await fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const remediation =
      typeof data.remediation === 'string' && data.remediation.trim()
        ? ` ${data.remediation.trim()}`
        : '';
    const error = new Error(
      `${data.error || 'Unable to save settings'}${remediation}`.trim()
    );
    error.didPersist = data.persisted !== true;
    throw error;
  }

  if (data && data._persisted === false) {
    const error = new Error(
      'Settings update was accepted but not persisted. Verify filesystem permissions and retry.'
    );
    error.didPersist = false;
    throw error;
  }

  state.settings = data || state.settings;
  return data;
}

function onboardingState() {
  if (!state.settings || typeof state.settings !== 'object') {
    state.settings = {};
  }
  if (!state.settings.onboarding || typeof state.settings.onboarding !== 'object') {
    state.settings.onboarding = {};
  }
  if (!state.settings.onboarding.completed_steps) {
    state.settings.onboarding.completed_steps = {};
  }

  ONBOARDING_STEP_ORDER.forEach((step) => {
    if (typeof state.settings.onboarding.completed_steps[step] !== 'boolean') {
      state.settings.onboarding.completed_steps[step] = false;
    }
  });

  if (typeof state.settings.onboarding.dismissed !== 'boolean') {
    state.settings.onboarding.dismissed = false;
  }

  return state.settings.onboarding;
}

async function persistOnboardingState() {
  const onboarding = onboardingState();
  try {
    await saveSettings({
      onboarding: {
        dismissed: onboarding.dismissed,
        completed_steps: onboarding.completed_steps,
      },
    });
  } catch (error) {
    console.warn('Unable to persist onboarding state', error);
  }
}

function markOnboardingStepComplete(step) {
  if (!ONBOARDING_STEP_ORDER.includes(step)) {
    return;
  }
  const onboarding = onboardingState();
  if (onboarding.completed_steps[step]) {
    return;
  }
  onboarding.completed_steps[step] = true;
  void persistOnboardingState();
  renderOnboardingPanel();
}

function isSetupIncomplete() {
  if (state.settings?.preference_setup_required === true) {
    return true;
  }

  const setupComplete = state.settings?.preferences?.webui?.setup_complete;
  return setupComplete === false;
}

function linkChecklistAction(step) {
  if (step === 'set_preferences') {
    openSettingsModal();
    return;
  }

  if (step === 'add_first_series') {
    dom.addEntry?.click();
    return;
  }

  if (step === 'preview_card') {
    const firstEntry = state.entries[0];
    if (!firstEntry) {
      showToast('Add a series entry first so you can generate a preview.', 'info');
      return;
    }
    openPreview(firstEntry);
    return;
  }

  if (step === 'save_config') {
    void saveConfiguration();
    return;
  }

  if (step === 'run_build') {
    dom.runBuilder?.click();
  }
}

function renderOnboardingPanel() {
  if (!dom.onboarding) {
    return;
  }

  const onboarding = onboardingState();
  onboarding.completed_steps.set_preferences = !isSetupIncomplete();
  onboarding.completed_steps.add_first_series = state.entries.length > 0;

  const showOnboarding = isSetupIncomplete() || state.entries.length === 0;
  dom.onboarding.hidden = !showOnboarding || onboarding.dismissed;
  dom.onboarding.innerHTML = '';

  if (dom.onboarding.hidden) {
    return;
  }

  const panel = document.createElement('section');
  panel.className = 'onboarding-panel';
  panel.setAttribute('aria-label', 'Getting started checklist');

  const title = document.createElement('h2');
  title.textContent = 'Get started in 5 quick steps';

  const helper = document.createElement('p');
  helper.className = 'helper-text';
  helper.textContent =
    'Complete setup and generate your first title cards using the checklist below.';

  const list = document.createElement('ol');
  list.className = 'onboarding-checklist';

  const steps = [
    { key: 'set_preferences', label: 'Set preferences', action: 'Open settings' },
    { key: 'add_first_series', label: 'Add first series', action: 'Add entry' },
    { key: 'preview_card', label: 'Preview card', action: 'Open preview' },
    { key: 'save_config', label: 'Save config', action: 'Save config' },
    { key: 'run_build', label: 'Run build', action: 'Run build' },
  ];

  steps.forEach((step) => {
    const item = document.createElement('li');
    item.className = 'onboarding-step';
    item.classList.toggle('onboarding-step--complete', onboarding.completed_steps[step.key] === true);

    const status = document.createElement('span');
    status.className = 'onboarding-step__status';
    status.textContent = onboarding.completed_steps[step.key] ? 'Done' : 'Pending';

    const text = document.createElement('span');
    text.className = 'onboarding-step__label';
    text.textContent = step.label;

    const actionButton = document.createElement('button');
    actionButton.type = 'button';
    actionButton.className = 'onboarding-step__action';
    actionButton.textContent = step.action;
    actionButton.addEventListener('click', () => linkChecklistAction(step.key));

    item.append(status, text, actionButton);
    list.appendChild(item);
  });

  const dismiss = document.createElement('button');
  dismiss.type = 'button';
  dismiss.className = 'onboarding-dismiss';
  dismiss.textContent = 'Dismiss checklist';
  dismiss.addEventListener('click', () => {
    onboarding.dismissed = true;
    dom.onboarding.hidden = true;
    void persistOnboardingState();
  });

  panel.append(title, helper, list, dismiss);
  dom.onboarding.appendChild(panel);
}

async function convertLegacyTvYaml() {
  const response = await fetch('/api/tv/convert-legacy', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || 'Unable to convert tv.yml');
  }

  return response.json();
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

function isTextEditingElement(target) {
  if (!(target instanceof Element)) {
    return false;
  }
  if (target instanceof HTMLTextAreaElement) {
    return true;
  }
  if (target instanceof HTMLInputElement) {
    const type = (target.type || 'text').toLowerCase();
    return !['button', 'checkbox', 'color', 'file', 'hidden', 'radio', 'range', 'reset', 'submit'].includes(type);
  }
  if (target instanceof HTMLElement && target.isContentEditable) {
    return true;
  }
  const editableParent = target.closest('textarea, input, [contenteditable="true"]');
  return Boolean(editableParent);
}

function focusSearchField() {
  if (!dom.search) {
    return;
  }
  setSearchVisibility(true);
  dom.search.focus();
  dom.search.select();
}

function commandDefinitions() {
  return [
    {
      id: 'save',
      label: 'Save configuration',
      shortcuts: ['Ctrl/Cmd+S'],
      run: () => saveConfiguration(),
    },
    {
      id: 'search',
      label: 'Focus search',
      shortcuts: ['/', 'Ctrl/Cmd+K'],
      run: () => focusSearchField(),
    },
    {
      id: 'add',
      label: 'Add entry',
      shortcuts: ['A'],
      run: () => openAddEntryModal(),
    },
    {
      id: 'settings',
      label: 'Open settings',
      shortcuts: ['S', 'Ctrl/Cmd+,'],
      run: () => openSettingsModal(),
    },
  ];
}

function openCommandPaletteModal() {
  const modal = buildModal('Command palette');
  addFloatingCloseButton(modal, 'Close command palette');

  const intro = document.createElement('p');
  intro.className = 'helper-text';
  intro.textContent = 'Run an action quickly with keyboard shortcuts.';

  const list = document.createElement('div');
  list.className = 'modal-section';

  commandDefinitions().forEach((command) => {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'search-result';
    row.addEventListener('click', () => {
      closeModal(modal.element);
      command.run();
    });

    const summary = document.createElement('div');
    summary.className = 'search-result-summary';
    summary.innerHTML = `<h3>${command.label}</h3><p class="helper-text">${command.shortcuts.join(' · ')}</p>`;

    row.appendChild(summary);
    list.appendChild(row);
  });

  modal.content.append(intro, list);
  modal.footer.append(closeButton(() => closeModal(modal.element)));
}

function handleKeyboardShortcuts(event) {
  if (event.defaultPrevented) {
    return;
  }

  const hasModifier = event.ctrlKey || event.metaKey;
  const normalizedKey = typeof event.key === 'string' ? event.key.toLowerCase() : '';
  const isTyping = isTextEditingElement(event.target);

  if (isTyping) {
    return;
  }

  if (hasModifier && normalizedKey === 's') {
    event.preventDefault();
    saveConfiguration();
    return;
  }

  if (hasModifier && normalizedKey === 'k') {
    event.preventDefault();
    focusSearchField();
    return;
  }

  if (hasModifier && normalizedKey === ',') {
    event.preventDefault();
    openSettingsModal();
    return;
  }

  if (normalizedKey === '/') {
    event.preventDefault();
    focusSearchField();
    return;
  }

  if (normalizedKey === 'a') {
    event.preventDefault();
    openAddEntryModal();
    return;
  }

  if (normalizedKey === 's') {
    event.preventDefault();
    openSettingsModal();
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
    dom.runBuilder.addEventListener('click', () => {
      if (state.isDirty) {
        showToast('You have unsaved changes. Save before building.', 'warning');
        return;
      }
      triggerServerAction(
        dom.runBuilder,
        '/api/actions/build',
        'Builder run complete',
        {
          workingLabel: 'Building...',
          refresh: true,
          onSuccess: () => {
            markOnboardingStepComplete('run_build');
            refreshEntryPreviews(undefined, { cacheBust: true });
          },
        }
      );
    });
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

  document.addEventListener('keydown', handleKeyboardShortcuts);
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

  const createActionButton = (label, description, icon, handler, variant) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'entry-action-card';
    if (variant) {
      button.classList.add(`entry-action-card--${variant}`);
    }

    const iconElement = document.createElement('span');
    iconElement.className = 'material-symbols-rounded';
    iconElement.textContent = icon;

    const text = document.createElement('span');
    text.className = 'entry-action-card__text';

    const title = document.createElement('span');
    title.className = 'entry-action-card__title';
    title.textContent = label;

    const desc = document.createElement('span');
    desc.className = 'entry-action-card__description';
    desc.textContent = description;

    text.append(title, desc);
    button.append(iconElement, text);
    button.addEventListener('click', handler);

    return button;
  };

  const downloadButton = createActionButton(
    'Download sources',
    'Fetch latest metadata and artwork',
    'cloud_download',
    () =>
      triggerServerAction(
        downloadButton,
        '/api/actions/download-series-sources',
        `Downloaded sources for ${entry.name}`,
        { workingLabel: 'Downloading...', refresh: false, payload: entryPayload() }
      )
  );

  const revertButton = createActionButton(
    'Revert cards',
    'Restore cards back to the last saved set',
    'history',
    () =>
      queueDestructiveAction({
        key: `revert-series:${entry.id}`,
        label: `Queued “Revert cards” for ${entry.name}`,
        onCommit: () =>
          triggerServerAction(
            revertButton,
            '/api/actions/revert-series',
            `Reverted cards for ${entry.name}`,
            { workingLabel: 'Reverting...', refresh: false, payload: entryPayload() }
          ),
      })
  );

  const forgetButton = createActionButton(
    'Forget cards',
    'Clear loaded cards and metadata cache',
    'layers_clear',
    () =>
      queueDestructiveAction({
        key: `forget-cards:${entry.id}`,
        label: `Queued “Forget cards” for ${entry.name}`,
        onCommit: () =>
          triggerServerAction(
            forgetButton,
            '/api/actions/forget-cards',
            `Forgot loaded cards for ${entry.name}`,
            { workingLabel: 'Forgetting...', refresh: false, payload: entryPayload() }
          ),
      })
  );

  const deleteButton = createActionButton(
    'Delete cards',
    'Remove generated cards for this series',
    'delete_forever',
    () =>
      queueDestructiveAction({
        key: `delete-series-cards:${entry.id}`,
        label: `Queued “Delete cards” for ${entry.name}`,
        onCommit: () =>
          triggerServerAction(
            deleteButton,
            '/api/actions/delete-series-cards',
            `Deleted cards for ${entry.name}`,
            { workingLabel: 'Deleting...', refresh: false, payload: entryPayload() }
          ),
      }),
    'danger'
  );

  const freshBuildButton = createActionButton(
    'Fresh Build',
    'Delete, forget, and rebuild every card for this series',
    'autorenew',
    () =>
      queueDestructiveAction({
        key: `fresh-build-series:${entry.id}`,
        label: `Queued “Fresh Build” for ${entry.name}`,
        onCommit: () =>
          triggerServerAction(
            freshBuildButton,
            '/api/actions/fresh-build-series',
            `Fresh build complete for ${entry.name}`,
            {
              workingLabel: 'Fresh building...',
              refresh: false,
              payload: entryPayload(),
              onSuccess: () => refreshEntryPreviews([entry], { cacheBust: true }),
            }
          ),
      }),
    'danger'
  );

  actions.append(downloadButton, revertButton, forgetButton, deleteButton, freshBuildButton);
  modal.content.appendChild(actions);

  const dismiss = closeButton(() => closeModal(modal.element));
  modal.footer.appendChild(dismiss);
}

// -----------------------------------------------------------------------------
// Rendering
// -----------------------------------------------------------------------------
function renderEntries() {
  state.validationIssues.clear();
  updateSaveButtonDisabledState();
  refreshDirtyState();
  renderOnboardingPanel();
  dom.entries.innerHTML = '';

  const filtered = state.entries.filter((entry) =>
    entry.name.toLowerCase().includes(state.filter)
  );

  if (filtered.length === 0) {
    if (state.entries.length === 0) {
      const empty = createActionableEmptyState({
        title: 'No series entries yet',
        message:
          'Add your first series to get started. If previews fail later, verify Plex library name and save your settings.',
        primaryLabel: 'Add first series',
        primaryAction: () => dom.addEntry?.click(),
        secondaryLabel: 'Setup help',
        secondaryHref: HELP_LINKS.gettingStarted,
      });
      dom.entries.appendChild(empty);
    } else {
      const empty = createActionableEmptyState({
        title: 'No series match this search',
        message:
          'Try a different title or include a year suffix (for example, “Show Name (2024)”).',
        primaryLabel: 'Clear search',
        primaryAction: () => {
          state.filter = '';
          if (dom.search) {
            dom.search.value = '';
            dom.search.focus();
          }
          renderEntries();
        },
        secondaryLabel: 'Search tips',
        secondaryHref: HELP_LINKS.gettingStarted,
      });
      dom.entries.appendChild(empty);
    }
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

function createActionableEmptyState({
  title,
  message,
  primaryLabel,
  primaryAction,
  secondaryLabel,
  secondaryHref,
  compact = false,
}) {
  const block = document.createElement('section');
  block.className = `actionable-empty-state${compact ? ' actionable-empty-state--compact' : ''}`;

  const heading = document.createElement('h3');
  heading.className = 'actionable-empty-state__title';
  heading.textContent = title;

  const description = document.createElement('p');
  description.className = 'actionable-empty-state__message helper-text';
  description.textContent = message;

  const actions = document.createElement('div');
  actions.className = 'actionable-empty-state__actions';

  const primary = document.createElement('button');
  primary.type = 'button';
  primary.className = 'primary';
  primary.textContent = primaryLabel;
  primary.addEventListener('click', primaryAction);

  const secondary = document.createElement('a');
  secondary.className = 'actionable-empty-state__link';
  secondary.href = secondaryHref;
  secondary.target = '_blank';
  secondary.rel = 'noopener noreferrer';
  secondary.textContent = secondaryLabel;

  actions.append(primary, secondary);
  block.append(heading, description, actions);
  return block;
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
  entry.config = entry.config || {};
  initializeEntryPreviewState(entry);

  const removeEntryButton = document.createElement('button');
  removeEntryButton.type = 'button';
  removeEntryButton.className = 'entry-remove remove-button';
  removeEntryButton.setAttribute('aria-label', `Remove ${entry.name}`);
  removeEntryButton.textContent = '✕';
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
    logo.classList.toggle('entry-logo--light-surface', !isDarkBackground);
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

  const previewGroup = document.createElement('div');
  previewGroup.className = 'entry-preview-group';
  previewGroup.append(preview);

  const media = document.createElement('div');
  media.className = 'entry-media';
  media.append(logoWrapper, previewGroup);

  const titleInput = document.createElement('input');
  titleInput.type = 'text';
  titleInput.value = entry.name;
  const titleValidation = document.createElement('p');
  titleValidation.className = 'helper-text field-validation__message';
  titleValidation.hidden = true;
  titleInput.addEventListener('input', (event) => {
    entry.name = event.target.value;
  });
  titleInput.addEventListener('focus', () => {
    titleInput.dataset.originalName = entry.name;
  });
  titleInput.addEventListener('blur', async () => {
    const originalName = titleInput.dataset.originalName;
    if (originalName && originalName !== entry.name) {
      moveLogoBackgroundPreference(originalName, entry.name);
      syncLogoBackground();
      await Promise.all([
        evictSeriesPreviewCache(originalName),
        evictSeriesPreviewCache(entry.name),
      ]);
    }
    sortEntries();
    state.pendingEntryId = entry.id;
    renderEntries();
  });

  const titleContainer = document.createElement('div');
  titleContainer.className = 'entry-title';
  titleContainer.append(titleInput, titleValidation);
  attachFieldValidation({
    input: titleInput,
    messageNode: titleValidation,
    entry,
    fieldId: '__entry_name__',
    validators: [validateYearSuffix],
  });

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
        onSuccess: () => refreshEntryPreviews([entry], { cacheBust: true }),
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

  const retryPreviewEpisodeLoad = () => {
    entry.previewEpisodeStatus = 'idle';
    syncPreviewEpisodeControls();
    ensurePreviewEpisodes(entry, syncPreviewEpisodeControls);
  };

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

    let statusText = '';
    if (entry.previewEpisodeStatus === 'loading') {
      statusText = 'Loading episodes…';
    } else if (entry.previewEpisodeStatus === 'error') {
      statusText = 'Episode list unavailable; random preview remains available.';
    }

    previewEpisodeStatus.textContent = statusText;
    previewEpisodeStatus.hidden = !statusText;
    previewEpisodeSelect.disabled = entry.previewEpisodeStatus === 'loading';
  };

  previewEpisodeSelect.addEventListener('change', async () => {
    syncPreviewEpisodeConfig(entry, previewEpisodeSelect.value);
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

  const previewActions = document.createElement('div');
  previewActions.className = 'entry-preview-actions';
  previewActions.append(buildButton, manageButton);

  previewGroup.append(previewActions);

  actions.append(previewControls);
  header.append(summary, actions);

  const body = document.createElement('div');
  body.className = 'entry-body';
  const entryVisibilityMode = getEntryVisibilityMode(entry);

  const visibilityControls = document.createElement('div');
  visibilityControls.className = 'entry-visibility-controls';

  const visibilityLabel = document.createElement('span');
  visibilityLabel.className = 'helper-text';
  visibilityLabel.textContent = 'Fields';

  const visibilityToggle = document.createElement('button');
  visibilityToggle.type = 'button';
  visibilityToggle.className = 'add-line add-line--inline';
  visibilityToggle.textContent =
    entryVisibilityMode === 'advanced' ? 'Showing advanced' : 'Showing basic';
  visibilityToggle.addEventListener('click', () => {
    const nextMode = getEntryVisibilityMode(entry) === 'advanced' ? 'basic' : 'advanced';
    setEntryVisibilityMode(entry, nextMode);
    renderEntries();
  });

  visibilityControls.append(visibilityLabel, visibilityToggle);
  body.appendChild(visibilityControls);

  const usedFields = new Set();
  const generalFieldRows = [];
  const fontFieldRows = [];
  let libraryFieldRow = null;
  state.fields.forEach((field) => {
    if (field.id === 'extras') {
      return;
    }
    const value = getValue(entry.config, field.path);
    if (ID_FIELDS.has(field.id)) {
      return;
    }
    if (value !== undefined) {
      if (!isFieldVisibleForMode(field, entryVisibilityMode)) {
        return;
      }
      usedFields.add(field.id);
      const row = renderFieldRow(entry, field, value);
      if (field.id === 'library') {
        libraryFieldRow = { field, row };
      } else if (field.path?.[0] === 'font') {
        fontFieldRows.push({ field, row });
      } else {
        generalFieldRows.push({ field, row });
      }
    }
  });

  const extraFields = configuredExtraFields(entry);
  extraFields.forEach((field) => {
    const value = getValue(entry.config, field.path);
    if (value === undefined) {
      return;
    }
    if (!isFieldVisibleForMode(field, entryVisibilityMode)) {
      return;
    }
    const row = renderFieldRow(entry, field, value);
    if (isFontExtraField(field)) {
      fontFieldRows.push({ field, row });
    } else {
      generalFieldRows.push({ field, row });
    }
  });

  const identifierSection =
    entryVisibilityMode === 'advanced' ? renderIdentifierSection(entry) : null;
  if (identifierSection) {
    body.appendChild(identifierSection);
  }

  if (libraryFieldRow) {
    body.appendChild(libraryFieldRow.row);
  }

  generalFieldRows
    .sort((a, b) => compareFieldOptions(a.field, b.field))
    .forEach(({ row }) => body.appendChild(row));

  const fontSection = document.createElement('section');
  fontSection.className = 'entry-section entry-section--font';

  const fontHeader = document.createElement('div');
  fontHeader.className = 'entry-section__header';

  const fontTitle = document.createElement('h3');
  fontTitle.className = 'entry-section__title';
  fontTitle.textContent = 'Font';

  fontHeader.append(fontTitle);

  const fontFieldsContainer = document.createElement('div');
  fontFieldsContainer.className = 'entry-section__fields';
  if (fontFieldRows.length === 0) {
    const helper = document.createElement('p');
    helper.className = 'helper-text entry-section__empty';
    helper.textContent = 'No font options added yet. Add lines to configure typography.';
    fontFieldsContainer.appendChild(helper);
  } else {
    fontFieldRows
      .sort((a, b) => compareFieldOptions(a.field, b.field))
      .forEach(({ row }) => fontFieldsContainer.appendChild(row));
  }

  const fontFooter = document.createElement('div');
  fontFooter.className = 'entry-section__footer';

  const addFontLineButton = document.createElement('button');
  addFontLineButton.className = 'add-line add-line--inline';
  addFontLineButton.textContent = '+ Add font line';
  addFontLineButton.addEventListener('click', () =>
    openFieldSelector(entry, {
      title: 'Add font line',
      emptyMessage: 'All font options are already configured for this entry.',
      availableFilter: (field) =>
        (field.path?.[0] === 'font' || (field.isExtra && isFontExtraField(field))) &&
        isFieldVisibleForMode(field, getEntryVisibilityMode(entry)),
    })
  );

  fontFooter.appendChild(addFontLineButton);

  fontSection.append(fontHeader, fontFieldsContainer, fontFooter);
  body.appendChild(fontSection);

  const addLineControls = document.createElement('div');
  addLineControls.className = 'add-line-controls add-line-controls--footer';

  const addLineButton = document.createElement('button');
  addLineButton.type = 'button';
  addLineButton.className = 'icon-button add-line-button';
  addLineButton.setAttribute('aria-label', 'Add new line');
  addLineButton.innerHTML =
    '<span class="material-symbols-rounded" aria-hidden="true">add</span>';
  addLineButton.addEventListener('click', () =>
    openFieldSelector(entry, {
      availableFilter: (field) =>
        field.path?.[0] !== 'font' &&
        !ID_FIELDS.has(field.id) &&
        !isFontExtraField(field) &&
        isFieldVisibleForMode(field, getEntryVisibilityMode(entry)),
    })
  );

  const addLineSearchButton = document.createElement('button');
  addLineSearchButton.type = 'button';
  addLineSearchButton.className = 'icon-button add-line-button add-line-search__button';
  addLineSearchButton.setAttribute('aria-label', 'Search configuration options');
  addLineSearchButton.innerHTML =
    '<span class="material-symbols-rounded" aria-hidden="true">search</span>';

  addLineSearchButton.addEventListener('click', () => openOptionSearch(entry));

  addLineControls.append(addLineButton, addLineSearchButton);
  body.appendChild(addLineControls);

  container.append(header, body);
  return container;
}

let previewObserver = null;
const previewLoadOptions = new WeakMap();

function previewUrlForEntry(entry, { cacheBust = false } = {}) {
  if (!entry) {
    return null;
  }

  const providedUrl =
    entry.previewUrl || entry.preview_url || entry.config?.previewUrl || entry.config?.preview_url;
  if (providedUrl) {
    const separator = providedUrl.includes('?') ? '&' : '?';
    return cacheBust ? `${providedUrl}${separator}_=${Date.now()}` : providedUrl;
  }

  const params = new URLSearchParams();
  const slug = resolveEntrySlug(entry);
  if (slug) {
    params.set('slug', slug);
  }
  if (entry?.name) {
    params.set('name', entry.name);
  }

  const previewEpisode = resolvePreviewEpisode(entry);
  if (previewEpisode && previewEpisode !== 'random') {
    params.set('previewEpisode', previewEpisode);
  }

  const season = previewSeasonForEntry(entry, previewEpisode);
  if (season || season === 0) {
    params.set('season', season);
  }

  if (cacheBust) {
    params.set('_', Date.now().toString());
  }

  const query = params.toString();
  if (!query) {
    return null;
  }

  return `/api/preview/static?${query}`;
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

  const hasPreview = Boolean(entry.previewSrc);
  const isLoading = Boolean(entry.previewLoading);
  const hasError = Boolean(entry.previewError);
  let statusText = '';

  wrapper.classList.remove(
    'entry-preview--error',
    'entry-preview--loaded',
    'entry-preview--refreshing',
    'entry-preview--loading'
  );
  wrapper.dataset.previewSrc = entry.previewSrc || '';
  wrapper.classList.toggle('entry-preview--loading', isLoading);

  if (image) {
    if (hasPreview) {
      if (image.src !== entry.previewSrc) {
        image.src = entry.previewSrc;
      }
      image.alt = `${entry.name} preview`;
      wrapper.classList.add('entry-preview--loaded');
    } else {
      image.removeAttribute('src');
    }
  }

  if (hasError) {
    statusText = entry.previewError;
    wrapper.classList.add('entry-preview--error');
  } else if (!hasPreview || isLoading) {
    statusText = 'Loading preview...';
  }

  if (placeholder) {
    placeholder.textContent = statusText;
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
          void loadEntryPreview(match);
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
  if (!entry || entry.previewLoading) {
    return;
  }

  if (entry.previewSrc) {
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

async function invalidateEntryPreview(entry, options = {}) {
  if (!entry) {
    return;
  }
  const { cacheBust = false } = options;
  entry.previewForceCacheBust = Boolean(cacheBust);
  entry.previewError = null;
  entry.previewSrc = null;
  entry.previewLoading = false;
  updateEntryPreview(entry);
  observeEntryPreview(entry);
}

async function loadEntryPreview(entry, options = {}) {
  if (!entry || entry.previewLoading) {
    return;
  }
  const { cacheBust = false } = options;
  const forceCacheBust = Boolean(cacheBust || entry.previewForceCacheBust);
  entry.previewForceCacheBust = false;

  const requestId = (entry.previewRequestId || 0) + 1;
  entry.previewRequestId = requestId;
  entry.previewLoading = true;
  entry.previewError = null;
  updateEntryPreview(entry);

  const src = previewUrlForEntry(entry, { cacheBust: forceCacheBust });
  if (!src) {
    entry.previewError = 'Preview unavailable';
    entry.previewLoading = false;
    updateEntryPreview(entry);
    return;
  }

  const image = new Image();
  image.onload = () => {
    if (entry.previewRequestId !== requestId) {
      return;
    }
    entry.previewSrc = src;
    entry.previewLoading = false;
    entry.previewError = null;
    updateEntryPreview(entry);
  };
  image.onerror = () => {
    if (entry.previewRequestId !== requestId) {
      return;
    }
    entry.previewError = 'Preview unavailable';
    entry.previewLoading = false;
    updateEntryPreview(entry);
  };

  image.src = src;
}

function requestEntryPreviews(entries = state.entries) {
  entries.forEach((entry) => {
    observeEntryPreview(entry);
  });
}

async function refreshEntryPreviews(entries = state.entries, options = {}) {
  await Promise.all(entries.map((entry) => invalidateEntryPreview(entry, options)));
  requestEntryPreviews(entries);
}

function schedulePreviewRefresh(entry, options = {}) {
  if (!entry) {
    return;
  }

  const { preferExisting = false, delay } = options;
  if (preferExisting && entry.previewSrc && !entry.previewError) {
    return;
  }

  if (entry.previewRefreshTimeout) {
    clearTimeout(entry.previewRefreshTimeout);
    entry.previewRefreshTimeout = null;
  }

  if (!delay && delay !== 0) {
    void refreshEntryPreviews([entry]);
    return;
  }

  entry.previewRefreshTimeout = setTimeout(() => {
    entry.previewRefreshTimeout = null;
    void refreshEntryPreviews([entry]);
  }, delay);
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
    const hasExistingEpisodeOptions =
      Array.isArray(entry.previewEpisodeOptions) &&
      entry.previewEpisodeOptions.length > 0;
    if (!Array.isArray(entry.previewEpisodeOptions)) {
      entry.previewEpisodeOptions = [];
    }
    entry.previewEpisodeStatus = hasExistingEpisodeOptions ? 'loaded' : 'error';
    entry.previewEpisodeError = hasExistingEpisodeOptions
      ? null
      : error.message || 'Unable to load episodes';
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
  if (entry.previewEpisodeStatus === 'loaded') {
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
  label.appendChild(buildOptionLabel(field.label, field.description));

  const controls = document.createElement('div');
  controls.className = 'field-controls';
  const validationMessage = document.createElement('p');
  validationMessage.className = 'helper-text field-validation__message';
  validationMessage.hidden = true;

  const showRemoveButton =
    field.isExtra ||
    (field.type !== 'font' &&
      field.id !== 'library' &&
      field.id !== 'card_type' &&
      field.path?.[0] !== 'font');
  const removeButton = showRemoveButton ? document.createElement('button') : null;
  if (removeButton) {
    removeButton.textContent = '✕';
    removeButton.className = 'remove-button';
    removeButton.setAttribute('aria-label', `Remove ${field.label}`);
    removeButton.addEventListener('click', () => {
      removeField(entry, field);
    });
  }

  switch (field.type) {
    case 'text':
      controls.appendChild(textInput(entry, field, value, validationMessage));
      break;
    case 'color':
      controls.appendChild(colorInput(entry, field, value));
      break;
    case 'number':
      controls.appendChild(numberInput(entry, field, value, validationMessage));
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
      controls.appendChild(
        wrapSeasonTitlesControl(entry, field, value, seasonEditor(entry, field, value))
      );
      break;
    case 'range-map':
      controls.appendChild(mapEditor(entry, field, value, 'Name', 'Range'));
      break;
    case 'hide-seasons':
      controls.appendChild(hideSeasonsSelect(entry, field, value));
      break;
    default:
      controls.appendChild(textInput(entry, field, value, validationMessage));
      break;
  }

  controls.appendChild(validationMessage);

  if (removeButton) {
    controls.appendChild(removeButton);
  }
  row.append(label, controls);
  return row;
}

function buildOptionLabel(labelText, description) {
  const wrapper = document.createElement('span');
  wrapper.className = 'option-label';

  const text = document.createElement('span');
  text.textContent = labelText || '';
  wrapper.appendChild(text);

  if (!description) {
    return wrapper;
  }

  const infoIcon = createOptionInfoIcon(description, labelText);
  wrapper.appendChild(infoIcon);
  return wrapper;
}

function createOptionInfoIcon(description, labelText) {
  const titleText = labelText ? `${labelText}: ${description}` : description;
  const template = dom.optionInfoTemplate;
  const fromTemplate =
    template && template.content?.firstElementChild
      ? template.content.firstElementChild.cloneNode(true)
      : null;

  const icon = fromTemplate || document.createElement('span');
  icon.classList.add('option-info');
  icon.setAttribute('aria-hidden', 'false');
  icon.setAttribute('title', titleText);
  icon.setAttribute('aria-label', titleText);
  if (!fromTemplate) {
    icon.classList.add('material-symbols-rounded');
    icon.setAttribute('aria-hidden', 'false');
    icon.textContent = 'info';
  }
  return icon;
}

// -----------------------------------------------------------------------------
// Field renderers
// -----------------------------------------------------------------------------
function normalizeFontSize(value) {
  if (value === undefined || value === null) {
    return undefined;
  }

  const trimmed = value.toString().trim();
  if (trimmed === '') {
    return undefined;
  }

  const withoutPercent = trimmed.replace(/%+$/u, '').trim();
  if (withoutPercent === '') {
    return undefined;
  }

  return `${withoutPercent}%`;
}

function textInput(entry, field, value, validationMessageNode = null) {
  const input = document.createElement('input');
  input.type = 'text';
  input.value = field.id === 'font.size' ? normalizeFontSize(value) ?? '' : value ?? '';
  input.addEventListener('input', (event) => {
    const rawValue = event.target.value;
    if (field.id === 'font.size') {
      updateField(entry, field, rawValue.trim() === '' ? undefined : rawValue);
      return;
    }
    updateField(entry, field, rawValue || undefined);
  });
  if (field.id === 'font.size') {
    input.addEventListener('blur', () => {
      const normalized = normalizeFontSize(input.value);
      updateField(entry, field, normalized);
      input.value = normalized ?? '';
    });
  }
  if (field.id === 'episode_number_text_format') {
    enableEpisodeTextFormatHelper(input);
  }
  if (validationMessageNode) {
    const validators = validatorsForField(field);
    if (validators.length > 0) {
      attachFieldValidation({
        input,
        messageNode: validationMessageNode,
        entry,
        fieldId: field.id,
        validators,
      });
    }
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

function isEpisodeTextFontKey(key) {
  return key && key.toString().toLowerCase() === 'episode_text_font';
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

function numberInput(entry, field, value, validationMessageNode = null) {
  const input = document.createElement('input');
  input.type = 'number';
  input.value = value ?? '';
  input.addEventListener('input', (event) => {
    const raw = event.target.value.trim();
    const numeric = raw === '' ? undefined : Number(raw);
    updateField(entry, field, numeric);
  });
  if (validationMessageNode) {
    const validators = validatorsForField(field);
    if (validators.length > 0) {
      attachFieldValidation({
        input,
        messageNode: validationMessageNode,
        entry,
        fieldId: field.id,
        validators,
      });
    }
  }
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
      remove.className = 'item-remove remove-button';
      remove.textContent = '✕';
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

function fontPicker(entry, field, value, options = {}) {
  const { onChange, showRemove = true } = options;
  const wrapper = document.createElement('div');
  wrapper.className = 'font-picker';

  const input = document.createElement('input');
  input.type = 'text';
  input.value = value ?? '';
  input.className = 'font-picker__input';

  const uploadInput = document.createElement('input');
  uploadInput.type = 'file';
  uploadInput.accept = '.ttf,.otf,.woff,.woff2';
  uploadInput.style.display = 'none';

  const actions = document.createElement('div');
  actions.className = 'font-picker__actions';

  let remove;

  const syncRemoveState = () => {
    if (remove) {
      remove.disabled = !input.value;
    }
  };

  const setValue = (nextValue) => {
    input.value = nextValue ?? '';
    updateField(entry, field, nextValue);
    if (onChange) {
      onChange(nextValue);
    }
    syncRemoveState();
  };

  input.addEventListener('input', (event) => {
    const nextValue = event.target.value || undefined;
    setValue(nextValue);
  });

  const upload = document.createElement('button');
  upload.type = 'button';
  upload.classList.add('icon-button');
  upload.setAttribute('aria-label', 'Upload font file');
  upload.innerHTML =
    '<span class="material-symbols-rounded" aria-hidden="true">cloud_upload</span>';
  upload.addEventListener('click', () => uploadInput.click());

  uploadInput.addEventListener('change', async (event) => {
    const [file] = event.target.files || [];
    if (!file) return;

    const targetDirectory = PathParent(input.value) || state.fontDirectory;

    upload.disabled = true;
    const originalLabel = upload.innerHTML;
    upload.innerHTML =
      '<span class="material-symbols-rounded" aria-hidden="true">hourglass_top</span>';

    try {
      const { path } = await uploadFont(file, targetDirectory);
      if (path) {
        setValue(path);
        showToast(`Uploaded ${file.name}`, 'success');
      }
    } catch (error) {
      const message = error?.message || 'Upload failed';
      showToast(message, 'error');
    } finally {
      upload.disabled = false;
      upload.innerHTML = originalLabel;
      uploadInput.value = '';
    }
  });

  const browse = document.createElement('button');
  browse.type = 'button';
  browse.classList.add('icon-button');
  browse.setAttribute('aria-label', 'Browse font files');
  browse.innerHTML =
    '<span class="material-symbols-rounded" aria-hidden="true">folder_open</span>';
  browse.addEventListener('click', () => {
    openFontPickerModal({
      initialPath: PathParent(input.value) || state.fontDirectory,
      onSelect: (path) => {
        setValue(path);
      },
    });
  });

  if (showRemove) {
    remove = document.createElement('button');
    remove.type = 'button';
    remove.classList.add('icon-button', 'remove-button');
    remove.setAttribute('aria-label', 'Remove font line');
    remove.textContent = '✕';
    remove.addEventListener('click', () => {
      uploadInput.value = '';
      setValue(undefined);
    });
  }

  actions.append(upload, browse);
  if (remove) {
    actions.append(remove);
  }
  wrapper.append(input, uploadInput, actions);
  syncRemoveState();
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
      remove.className = 'item-remove remove-button';
      remove.textContent = '✕';
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

      const renderFontValue = isEpisodeTextFontKey(row.key);
      const renderColorValue = isColorFieldKey(row.key);
      let valueInput;
      if (renderFontValue) {
        const fieldForFont = {
          id: `extras.${row.key}`,
          label: options.formatKeyLabel ? options.formatKeyLabel(row.key) : row.key,
          path: ['extras', row.key],
          type: 'font',
        };
        valueInput = fontPicker(entry, fieldForFont, row.value, {
          onChange: (nextValue) => {
            row.value = nextValue;
            update();
          },
          showRemove: false,
        });
      } else if (renderColorValue) {
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
      remove.className = 'item-remove remove-button';
      remove.textContent = '✕';
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

function normalizeExtraDefinition(definition) {
  if (!definition) {
    return null;
  }
  if (typeof definition === 'string') {
    return {
      key: definition,
      label: formatExtraLabel(definition),
    };
  }
  return {
    ...definition,
    key: definition.key,
    label: definition.label || formatExtraLabel(definition.key),
    choices: Array.isArray(definition.choices) ? definition.choices : undefined,
  };
}

function normalizeExtraKey(key) {
  return (key || '').toString().trim().toLowerCase();
}

function isFontExtraKey(key) {
  if (!key) {
    return false;
  }
  const normalized = key.toString().toLowerCase();
  return (
    normalized.includes('font') ||
    normalized.includes('stroke') ||
    normalized.includes('kerning') ||
    normalized.includes('interline') ||
    normalized.includes('interword') ||
    normalized.includes('vertical_shift')
  );
}

function knownExtraKeys() {
  const keys = new Set();
  const extras = state.cardTypeExtras || {};
  Object.values(extras).forEach((list) => {
    (list || []).forEach((item) => {
      const key = typeof item === 'string' ? item : item?.key;
      if (key) {
        keys.add(normalizeExtraKey(key));
      }
    });
  });
  return keys;
}

function extrasForCardType(cardType) {
  const normalized = normalizeCardType(cardType);
  const availableExtras = state.cardTypeExtras || {};
  const extras =
    availableExtras[normalized] ||
    availableExtras[Object.keys(availableExtras).find((key) => normalizeCardType(key) === normalized)];
  if (!extras) {
    return [];
  }
  return extras
    .map((item) => normalizeExtraDefinition(item))
    .filter(Boolean);
}

function findExtraDefinition(cardType, key) {
  const extras = extrasForCardType(cardType);
  const normalizedKey = normalizeExtraKey(key);
  return extras.find((item) => normalizeExtraKey(item.key) === normalizedKey) || null;
}

function buildExtraField(key, definition) {
  const fieldType = (() => {
    if (definition?.choices?.length) {
      return 'choice';
    }
    if (definition?.expectedType === 'boolean') {
      return 'boolean';
    }
    if (definition?.expectedType === 'int' || definition?.expectedType === 'float') {
      return 'number';
    }
    if (isEpisodeTextFontKey(key)) {
      return 'font';
    }
    if (isColorFieldKey(key)) {
      return 'color';
    }
    return 'text';
  })();

  const choices = definition?.choices
    ? definition.choices.map((choice) => ({ value: choice, label: choice }))
    : undefined;

  return {
    id: `extras.${key}`,
    label: definition?.label || formatExtraLabel(key),
    path: ['extras', key],
    type: fieldType,
    choices,
    isExtra: true,
    extraKey: key,
  };
}

function isFontExtraField(field) {
  return Boolean(field?.isExtra && (field.type === 'font' || isFontExtraKey(field.extraKey)));
}

function configuredExtraFields(entry) {
  const cardType = getValue(entry.config, ['card_type']) || getDefaultCardType();
  const definitions = extrasForCardType(cardType);
  const definitionMap = new Map(
    definitions.map((definition) => [normalizeExtraKey(definition.key), definition])
  );
  const knownKeys = knownExtraKeys();
  const extrasValue = getValue(entry.config, ['extras']) || {};
  return Object.keys(extrasValue)
    .map((key) => {
      const normalizedKey = normalizeExtraKey(key);
      const definition = definitionMap.get(normalizedKey);
      if (!definition && knownKeys.has(normalizedKey)) {
        return null;
      }
      return buildExtraField(key, definition);
    })
    .filter(Boolean);
}

function availableExtraFields(entry) {
  const cardType = getValue(entry.config, ['card_type']) || getDefaultCardType();
  const definitions = extrasForCardType(cardType);
  const extrasValue = getValue(entry.config, ['extras']) || {};
  const existingKeys = new Set(Object.keys(extrasValue).map((key) => normalizeExtraKey(key)));
  return definitions
    .filter((definition) => !existingKeys.has(normalizeExtraKey(definition.key)))
    .map((definition) => buildExtraField(definition.key, definition));
}

function openCustomExtraModal(entry) {
  const modal = buildModal('Add custom extra');
  addFloatingCloseButton(modal, 'Close custom extra dialog');

  const wrapper = document.createElement('div');
  wrapper.className = 'field-selector';

  const helper = document.createElement('p');
  helper.className = 'helper-text';
  helper.textContent = 'Enter a custom extra key to add it as a configurable line.';

  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = 'Custom extra key';
  input.className = 'modal-search';

  const error = document.createElement('p');
  error.className = 'helper-text';
  error.hidden = true;

  const addButton = document.createElement('button');
  addButton.type = 'button';
  addButton.textContent = 'Add extra';
  addButton.disabled = true;

  const updateState = () => {
    const key = input.value.trim();
    addButton.disabled = key === '';
    error.hidden = true;
  };

  input.addEventListener('input', updateState);

  const submit = () => {
    const key = input.value.trim();
    if (!key) {
      return;
    }
    const extrasValue = getValue(entry.config, ['extras']) || {};
    const normalizedKey = normalizeExtraKey(key);
    const existingKeys = Object.keys(extrasValue).map((existing) => normalizeExtraKey(existing));
    if (existingKeys.includes(normalizedKey)) {
      error.textContent = 'That extra key is already configured.';
      error.hidden = false;
      return;
    }
    const cardType = getValue(entry.config, ['card_type']) || getDefaultCardType();
    const definition = findExtraDefinition(cardType, key);
    const field = buildExtraField(key, definition);
    updateField(entry, field, defaultValueForField(field));
    closeModal(modal.element);
    renderEntries();
  };

  addButton.addEventListener('click', submit);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      submit();
    }
  });

  wrapper.append(helper, input, error);
  modal.content.appendChild(wrapper);
  modal.footer.append(addButton, closeButton(() => closeModal(modal.element)));

  requestAnimationFrame(() => input.focus());
}

function openExtrasPicker(cardType, rows, renderRows, updateRows) {
  const modal = buildModal('Add extra option');
  addFloatingCloseButton(modal, 'Close extra option selector');

  const wrapper = document.createElement('div');
  wrapper.className = 'card-type-modal';

  const optionsWrapper = document.createElement('div');
  optionsWrapper.className = 'search-results card-type-results';

  const available = extrasForCardType(cardType);
  const existingKeys = rows.map((row) => normalizeExtraKey(row.key)).filter(Boolean);
  const remaining = available.filter((item) => !existingKeys.includes(normalizeExtraKey(item.key)));

  if (remaining.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'helper-text';
    empty.textContent =
      available.length === 0
        ? 'No documented extras for this card type. You can still add a custom key.'
        : 'All available extras have already been added.';
    optionsWrapper.appendChild(empty);
  }

  remaining.forEach((definition) => {
    const option = document.createElement('button');
    option.type = 'button';
    option.className = 'card-type-option';
    option.textContent = formatExtraLabel(definition.label || definition.key);
    option.addEventListener('click', () => {
      rows.push({ key: definition.key, value: '' });
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

  wrapper.append(optionsWrapper, customWrapper);
  modal.content.appendChild(wrapper);
}

function extrasEditor(entry, field, value) {
  const cardType = getValue(entry.config, ['card_type']) || getDefaultCardType();
  const rows = Object.entries(value || {}).map(([key, val]) => ({ key, value: val }));

  const container = document.createElement('div');
  container.className = 'extras-list';

  const updateExtras = () => {
    const map = {};
    rows
      .filter((row) => row.key.trim() !== '')
      .forEach((row) => {
        map[row.key] = row.value ?? '';
      });
    updateField(entry, field, map);
  };

  const renderValueControl = (row) => {
    const definition = findExtraDefinition(cardType, row.key);
    const wrapper = document.createElement('div');
    wrapper.className = 'extra-card__value';

    const apply = (nextValue) => {
      row.value = nextValue;
      updateExtras();
    };

    const choices = definition?.choices;
    if (choices && choices.length > 0) {
      const select = document.createElement('select');
      select.className = 'extras-select';
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = 'Select value';
      placeholder.disabled = true;
      placeholder.selected = row.value === undefined || row.value === null || row.value === '';
      select.appendChild(placeholder);
      choices.forEach((choice) => {
        const opt = document.createElement('option');
        opt.value = choice;
        opt.textContent = choice;
        if (String(row.value) === String(choice)) {
          opt.selected = true;
          placeholder.selected = false;
        }
        select.appendChild(opt);
      });
      select.addEventListener('change', (event) => {
        apply(event.target.value);
      });
      wrapper.appendChild(select);
      return wrapper;
    }

    if (definition?.expectedType === 'boolean') {
      const select = document.createElement('select');
      ['true', 'false'].forEach((option) => {
        const opt = document.createElement('option');
        opt.value = option;
        opt.textContent = option;
        if (String(row.value) === option) {
          opt.selected = true;
        }
        select.appendChild(opt);
      });
      select.addEventListener('change', (event) => {
        apply(event.target.value === 'true');
      });
      wrapper.appendChild(select);
      return wrapper;
    }

    if (isEpisodeTextFontKey(row.key)) {
      const fieldForFont = {
        id: `extras.${row.key}`,
        label: definition?.label || row.key,
        path: ['extras', row.key],
        type: 'font',
      };
      wrapper.appendChild(
        fontPicker(entry, fieldForFont, row.value, {
          onChange: (nextValue) => {
            apply(nextValue);
          },
          showRemove: false,
        })
      );
      return wrapper;
    }

    if (isColorFieldKey(row.key)) {
      const colorWrapper = document.createElement('div');
      colorWrapper.className = 'inline-actions color-input';

      const color = document.createElement('input');
      color.type = 'color';
      color.value = isValidHexColor(row.value) ? row.value : '#ffffff';

      const text = document.createElement('input');
      text.type = 'text';
      text.placeholder = '#RRGGBB';
      text.value = row.value ?? '';

      const setValue = (newValue) => {
        apply(newValue);
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

      colorWrapper.append(color, text);
      wrapper.appendChild(colorWrapper);
      return wrapper;
    }

    if (definition?.expectedType === 'int' || definition?.expectedType === 'float') {
      const input = document.createElement('input');
      input.type = 'number';
      input.step = definition.expectedType === 'float' ? 'any' : '1';
      input.value = row.value ?? '';
      input.addEventListener('input', (event) => {
        const raw = event.target.value;
        if (raw === '') {
          apply('');
          return;
        }
        apply(definition.expectedType === 'int' ? parseInt(raw, 10) : parseFloat(raw));
      });
      wrapper.appendChild(input);
      return wrapper;
    }

    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = row.key || 'Value';
    input.value = row.value ?? '';
    input.addEventListener('input', (event) => {
      apply(event.target.value);
    });
    wrapper.appendChild(input);
    return wrapper;
  };

  const renderRows = () => {
    container.innerHTML = '';
    rows.forEach((row, index) => {
      const definition = findExtraDefinition(cardType, row.key);
      const card = document.createElement('div');
      card.className = 'item-card extra-card';

      const header = document.createElement('div');
      header.className = 'extra-card__header';

      const title = document.createElement('div');
      title.className = 'extra-card__title';
      const optionLabel = definition?.label || formatExtraLabel(row.key);
      title.appendChild(buildOptionLabel(optionLabel, definition?.description));
      header.appendChild(title);

      if (definition) {
        const hint = document.createElement('div');
        hint.className = 'extra-card__hint';
        hint.textContent = row.key;
        header.appendChild(hint);
      } else {
        const keyGroup = document.createElement('div');
        keyGroup.className = 'extra-card__key-group';
        const keyLabel = document.createElement('div');
        keyLabel.className = 'extra-card__hint';
        keyLabel.textContent = 'Key';

        const keyInput = document.createElement('input');
        keyInput.type = 'text';
        keyInput.placeholder = 'Custom extra key';
        keyInput.value = row.key;
        keyInput.addEventListener('input', (event) => {
          row.key = event.target.value;
          updateExtras();
          renderRows();
        });

        keyGroup.append(keyLabel, keyInput);
        header.appendChild(keyGroup);
      }

      const controls = document.createElement('div');
      controls.className = 'extra-card__controls';

      controls.appendChild(renderValueControl(row));

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'item-remove item-remove--inline remove-button';
      remove.textContent = '✕';
      remove.setAttribute('aria-label', `Remove ${row.key || 'extra option'}`);
      remove.addEventListener('click', () => {
        rows.splice(index, 1);
        updateExtras();
        renderRows();
      });

      controls.appendChild(remove);
      card.append(header, controls);
      container.appendChild(card);
    });

    const add = document.createElement('button');
    add.textContent = '+ Add extra option';
    add.className = 'add-line add-line--inline';
    add.addEventListener('click', () => {
      openExtrasPicker(cardType, rows, renderRows, updateExtras);
    });
    container.appendChild(add);
  };

  renderRows();
  return container;
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

function wrapSeasonTitlesControl(entry, field, value, content) {
  const container = document.createElement('details');
  container.className = 'field-collapsible';

  const totalSeasons = Object.keys(value || {})
    .filter((key) => key !== 'hide')
    .length;
  if (entry.seasonTitlesCollapsed === undefined) {
    entry.seasonTitlesCollapsed = totalSeasons >= 6;
  }
  container.open = !entry.seasonTitlesCollapsed;

  const summary = document.createElement('summary');
  summary.className = 'field-collapsible__summary';

  const summaryLabel = document.createElement('span');
  summaryLabel.className = 'field-collapsible__label';
  summaryLabel.textContent = entry.seasonTitlesCollapsed
    ? '+'
    : '-';

  const summaryMeta = document.createElement('span');
  summaryMeta.className = 'field-collapsible__meta';
  summaryMeta.textContent = `${totalSeasons || 0} title${totalSeasons === 1 ? '' : 's'}`;

  summary.append(summaryLabel, summaryMeta);

  const contentWrapper = document.createElement('div');
  contentWrapper.className = 'field-collapsible__content';
  contentWrapper.appendChild(content);

  container.append(summary, contentWrapper);

  container.addEventListener('toggle', () => {
    entry.seasonTitlesCollapsed = !container.open;
    summaryLabel.textContent = entry.seasonTitlesCollapsed
      ? '+'
      : '-';
  });

  return container;
}

// -----------------------------------------------------------------------------
// Field manipulation helpers
// -----------------------------------------------------------------------------
function shouldForcePreviewRefresh(field) {
  if (!field) {
    return false;
  }
  if (PREVIEW_FORCE_FIELDS.has(field.id)) {
    return true;
  }
  return field.path?.[0] === 'font' || field.path?.[0] === 'extras';
}

function handleEntryConfigChange(entry, field) {
  if (!entry || !field || PREVIEW_NEUTRAL_FIELDS.has(field.id)) {
    return;
  }
  const forceRefresh = shouldForcePreviewRefresh(field);
  schedulePreviewRefresh(entry, {
    preferExisting: !forceRefresh,
    delay: forceRefresh ? 300 : 700,
  });
}

function updateField(entry, field, value) {
  if (value === undefined) {
    removeField(entry, field);
    return;
  }
  setValue(entry.config, field.path, value);
  handleEntryConfigChange(entry, field);
  refreshDirtyState();
}

function removeField(entry, field) {
  deleteValue(entry.config, field.path);
  handleEntryConfigChange(entry, field);
  refreshDirtyState();
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

function applyIdentifierValue(entry, field, rawValue) {
  if (!entry || !field) {
    return;
  }
  const value = rawValue === undefined || rawValue === null ? '' : String(rawValue).trim();
  if (value === '') {
    deleteValue(entry.config, field.path);
    handleEntryConfigChange(entry, field);
    refreshDirtyState();
    return;
  }

  if (field.type === 'number') {
    const numeric = Number(value);
    setValue(entry.config, field.path, Number.isFinite(numeric) ? numeric : value);
  } else {
    setValue(entry.config, field.path, value);
  }
  handleEntryConfigChange(entry, field);
  refreshDirtyState();
}

function createIdentifierInput(entry, field, value, onChange) {
  const input = document.createElement('input');
  input.type = 'text';
  input.value = value ?? '';
  const validationMessage = document.createElement('p');
  validationMessage.className = 'helper-text field-validation__message';
  validationMessage.hidden = true;
  if (field.type === 'number') {
    input.inputMode = 'numeric';
  }
  input.placeholder = field.label || field.id;
  input.addEventListener('input', () => {
    applyIdentifierValue(entry, field, input.value);
  });
  input.addEventListener('change', () => {
    if (typeof onChange === 'function') {
      onChange();
    }
  });
  const validators = validatorsForField(field);
  if (validators.length > 0) {
    attachFieldValidation({
      input,
      messageNode: validationMessage,
      entry,
      fieldId: field.id,
      validators,
    });
  }
  const wrapper = document.createElement('div');
  wrapper.className = 'field-validation';
  wrapper.append(input, validationMessage);
  return { input, wrapper };
}

// -----------------------------------------------------------------------------
// Additional UI components
// -----------------------------------------------------------------------------
const BASICS_FIELDS = new Set([
  'library',
  'card_type',
  'episode_number_text_format',
  'episode_number_text_case',
  'episode_data_source',
  'watched_style',
  'unwatched_style',
  'image_source_priority',
]);

const BASIC_ENTRY_FIELD_IDS = new Set([
  ...BASICS_FIELDS,
  'font.file',
  'font.size',
  'font.color',
  'font.case',
  'seasons.hide',
  'seasons.titles',
  'translation',
]);

const ENTRY_VISIBILITY_MODES = new Set(['basic', 'advanced']);

const ID_FIELDS = new Set([
  'tmdb_id',
  'tvdb_id',
  'imdb_id',
  'tvrage_id',
  'emby_id',
  'jellyfin_id',
  'sonarr_id',
]);

function normalizeEntryVisibilityMode(mode) {
  return ENTRY_VISIBILITY_MODES.has(mode) ? mode : 'basic';
}

function defaultEntryVisibilityMode() {
  return normalizeEntryVisibilityMode(state.settings?.entry_visibility_default_mode);
}

function getEntryVisibilityMode(entry) {
  if (!entry) {
    return defaultEntryVisibilityMode();
  }
  entry.visibilityMode = normalizeEntryVisibilityMode(entry.visibilityMode || defaultEntryVisibilityMode());
  return entry.visibilityMode;
}

function setEntryVisibilityMode(entry, mode) {
  if (!entry) {
    return;
  }
  entry.visibilityMode = normalizeEntryVisibilityMode(mode);
}

function fieldVisibilityTier(field) {
  if (!field) {
    return 'advanced';
  }
  if (field.tier === 'basic' || field.tier === 'advanced') {
    return field.tier;
  }
  if (field.isExtra) {
    return 'advanced';
  }
  return BASIC_ENTRY_FIELD_IDS.has(field.id) ? 'basic' : 'advanced';
}

function isFieldVisibleForMode(field, mode) {
  if (normalizeEntryVisibilityMode(mode) === 'advanced') {
    return true;
  }
  return fieldVisibilityTier(field) === 'basic';
}

function getIdentifierFields() {
  return state.fields.filter((field) => ID_FIELDS.has(field.id));
}

function isIdentifierValueSet(value) {
  return value !== undefined && value !== null && String(value).trim() !== '';
}

const PREVIEW_NEUTRAL_FIELDS = new Set(['library', ...ID_FIELDS]);
const PREVIEW_FORCE_FIELDS = new Set([
  'card_type',
  'episode_number_text_case',
  'episode_number_text_format',
  'extras',
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
  'episode_number_text_format',
  'episode_number_text_case',
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
    emptyMessage = 'All available options are already configured.',
    availableFilter,
  } = {}
) {
  const modal = buildModal(title);
  addFloatingCloseButton(modal, 'Close add field dialog');

  const baseFields = state.fields.filter((field) => field.id !== 'extras');
  const extraFields = availableExtraFields(entry);
  const customExtraField = {
    id: 'extras.custom',
    label: 'Custom extra',
    path: ['extras', 'custom'],
    type: 'extra',
    isCustomExtra: true,
    isExtra: true,
  };

  const available = [...baseFields, ...extraFields, customExtraField]
    .filter((field) => !availableFilter || availableFilter(field))
    .filter((field) => getValue(entry.config, field.path) === undefined || field.isCustomExtra)
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
        if (field.isCustomExtra) {
          closeModal(modal.element);
          openCustomExtraModal(entry);
          return;
        }
        const defaultValue = defaultValueForField(field);
        updateField(entry, field, defaultValue);
        closeModal(modal.element);
        renderEntries();
      });
    };

    search.addEventListener('input', render);
    render();

    wrapper.append(controls, groupsContainer, emptyState);
    modal.content.appendChild(wrapper);
  }

  modal.footer.appendChild(closeButton(() => closeModal(modal.element)));
}

function openOptionSearch(entry, initialTerm = '') {
  const modal = buildModal('Search options');
  addFloatingCloseButton(modal, 'Close option search dialog');
  const entryVisibilityMode = getEntryVisibilityMode(entry);

  const buildOptions = () => {
    const availableFields = state.fields.filter(
      (field) =>
        field.id !== 'extras' &&
        getValue(entry.config, field.path) === undefined &&
        !ID_FIELDS.has(field.id) &&
        isFieldVisibleForMode(field, entryVisibilityMode)
    );
    const availableExtras = availableExtraFields(entry).filter((field) =>
      isFieldVisibleForMode(field, entryVisibilityMode)
    );

    const options = [];

    availableFields.forEach((field) => {
      const category = field.path?.[0] === 'font' ? 'Font option' : 'Field';
      const metaParts = [field.type, field.path?.join(' › ')].filter(Boolean);
      options.push({
        id: field.id,
        label: field.label || field.id,
        category,
        meta: metaParts.join(' • '),
        keywords: [field.label, field.type, field.path?.join(' '), field.id]
          .filter(Boolean)
          .join(' ')
          .toLowerCase(),
        onSelect: () => {
          const defaultValue = defaultValueForField(field);
          updateField(entry, field, defaultValue);
          closeModal(modal.element);
          renderEntries();
        },
      });
    });

    availableExtras.forEach((extraField) => {
      const label = extraField.label || formatExtraLabel(extraField.extraKey);
      options.push({
        id: `extra:${extraField.extraKey}`,
        label,
        category: isFontExtraField(extraField) ? 'Font option' : 'Extra option',
        meta: `extras › ${extraField.extraKey}`,
        keywords: `${extraField.extraKey} ${label} extras extra option`.toLowerCase(),
        onSelect: () => {
          updateField(entry, extraField, defaultValueForField(extraField));
          closeModal(modal.element);
          renderEntries();
        },
      });
    });

    options.push({
      id: 'extra:custom',
      label: 'Custom extra',
      category: 'Extra option',
      meta: 'extras',
      keywords: 'custom extra extras option'.toLowerCase(),
      onSelect: () => {
        closeModal(modal.element);
        openCustomExtraModal(entry);
      },
    });

    return options;
  };

  const options = buildOptions();

  if (options.length === 0) {
    const message = document.createElement('p');
    message.className = 'helper-text';
    message.textContent = 'All available options are already configured.';
    modal.content.appendChild(message);
    modal.footer.appendChild(closeButton(() => closeModal(modal.element)));
    return;
  }

  const wrapper = document.createElement('div');
  wrapper.className = 'field-selector';

  const search = document.createElement('input');
  search.type = 'search';
  search.placeholder = 'Search fields, font options, and extras...';
  search.className = 'modal-search';
  search.value = initialTerm;

  const status = document.createElement('p');
  status.className = 'helper-text field-selector__status';

  const controls = document.createElement('div');
  controls.className = 'field-selector__controls';
  controls.append(search, status);

  const list = document.createElement('div');
  list.className = 'field-groups';

  const emptyState = document.createElement('div');
  emptyState.className = 'empty-state field-selector__empty';
  emptyState.textContent = 'No options match your search. Try a different term.';
  emptyState.hidden = true;

  const render = () => {
    const term = search.value.trim().toLowerCase();
    const terms = term.split(/\s+/).filter(Boolean);
    const filtered = options.filter((option) => {
      if (terms.length === 0) {
        return true;
      }
      return terms.every((part) => option.keywords.includes(part));
    });

    status.textContent = `${filtered.length} of ${options.length} options shown`;
    list.innerHTML = '';
    emptyState.hidden = filtered.length > 0;
    if (filtered.length === 0) {
      return;
    }

    filtered
      .sort((a, b) => (a.label || '').localeCompare(b.label || '', undefined, { sensitivity: 'base' }))
      .forEach((option) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'field-option';

        const title = document.createElement('span');
        title.className = 'field-option__title';
        title.textContent = option.label;

        const meta = document.createElement('span');
        meta.className = 'field-option__meta';
        const parts = [option.category, option.meta].filter(Boolean);
        meta.textContent = parts.join(' • ');

        button.append(title, meta);
        button.addEventListener('click', option.onSelect);
        list.appendChild(button);
      });
  };

  search.addEventListener('input', render);
  render();

  wrapper.append(controls, list, emptyState);
  modal.content.appendChild(wrapper);
  modal.footer.appendChild(closeButton(() => closeModal(modal.element)));

  requestAnimationFrame(() => {
    search.focus();
    search.select();
  });
}

function openIdentifierModal(entry) {
  const identifierFields = getIdentifierFields();
  const modal = buildModal('Metadata identifiers');
  addFloatingCloseButton(modal, 'Close metadata identifiers dialog');

  if (!identifierFields.length) {
    const message = document.createElement('p');
    message.className = 'helper-text';
    message.textContent = 'No metadata identifier fields are available.';
    modal.content.appendChild(message);
    modal.footer.append(closeButton(() => closeModal(modal.element)));
    return;
  }

  const description = document.createElement('p');
  description.className = 'helper-text';
  description.textContent = 'Provide IDs to link this series to external services.';

  const list = document.createElement('div');
  list.className = 'identifier-list';

  identifierFields.sort(compareFieldOptions).forEach((field) => {
    const row = document.createElement('div');
    row.className = 'field-row identifier-row';

    const label = document.createElement('label');
    label.textContent = field.label;

    const controls = document.createElement('div');
    controls.className = 'field-controls identifier-controls';

    const value = getValue(entry.config, field.path);
    const { input, wrapper: inputWrapper } = createIdentifierInput(entry, field, value);

    const clearButton = document.createElement('button');
    clearButton.type = 'button';
    clearButton.className = 'identifier-clear';
    clearButton.textContent = 'Clear';
    clearButton.addEventListener('click', () => {
      input.value = '';
      applyIdentifierValue(entry, field, '');
    });

    controls.append(inputWrapper, clearButton);
    row.append(label, controls);
    list.append(row);
  });

  modal.content.append(description, list);
  modal.footer.append(
    closeButton(() => {
      closeModal(modal.element);
      renderEntries();
    })
  );
}

function renderIdentifierSection(entry) {
  const identifierFields = getIdentifierFields();
  if (!identifierFields.length) {
    return null;
  }

  const section = document.createElement('section');
  section.className = 'entry-section entry-section--identifiers';

  const header = document.createElement('div');
  header.className = 'entry-section__header';

  const title = document.createElement('h3');
  title.className = 'entry-section__title';
  title.textContent = 'Metadata IDs';

  const editButton = document.createElement('button');
  editButton.className = 'add-line add-line--inline';
  editButton.textContent = 'Edit IDs';
  editButton.addEventListener('click', () => openIdentifierModal(entry));

  header.append(title, editButton);

  const summary = document.createElement('div');
  summary.className = 'identifier-summary';

  const setFields = identifierFields
    .map((field) => ({ field, value: getValue(entry.config, field.path) }))
    .filter(({ value }) => isIdentifierValueSet(value));

  if (setFields.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'helper-text identifier-empty';
    empty.textContent = 'No IDs set yet. Add them to improve matching.';
    summary.appendChild(empty);
  } else {
    setFields.forEach(({ field, value }) => {
      const pill = document.createElement('div');
      pill.className = 'identifier-pill';

      const label = document.createElement('span');
      label.className = 'identifier-pill__label';
      label.textContent = field.label;

      const val = document.createElement('span');
      val.className = 'identifier-pill__value';
      val.textContent = value;

      pill.append(label, val);
      summary.appendChild(pill);
    });
  }

  section.append(header, summary);
  return section;
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

    setStatus('');

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

function openBackupPickerModal({ initialPath = DEFAULT_BACKUP_DIRECTORY, onRestore } = {}) {
  const modal = buildModal('Load backup file');
  addFloatingCloseButton(modal, 'Close backup picker');

  const intro = document.createElement('p');
  intro.className = 'helper-text';
  intro.textContent = 'Choose a saved tv.yml backup to restore it.';

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

  modal.content.append(intro, header, status, grid);
  modal.footer.append(closeButton(() => closeModal(modal.element)));

  let currentPath = initialPath || DEFAULT_BACKUP_DIRECTORY;

  const setStatus = (message, tone = 'muted') => {
    status.textContent = message;
    status.dataset.tone = tone;
  };

  const renderEntries = (entries) => {
    grid.innerHTML = '';
    if (!entries.length) {
      setStatus('No backups found in this directory.', 'warning');
      return;
    }

    setStatus('Tap a backup to restore it.');

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
      .filter((entry) => entry.name && entry.name.toLowerCase().match(/\.ya?ml$/))
      .forEach((entry) => {
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'font-card font-card--file';

        const meta = document.createElement('div');
        meta.className = 'font-card__meta';

        const icon = document.createElement('div');
        icon.className = 'font-card__icon';
        icon.textContent = '📄';

        const title = document.createElement('div');
        title.className = 'font-card__name';
        title.textContent = entry.name;

        const hint = document.createElement('div');
        hint.className = 'font-card__hint';
        hint.textContent = 'Tap to load this backup';

        const detail = document.createElement('div');
        detail.className = 'font-card__hint';
        if (entry.modified) {
          const modified = new Date(entry.modified * 1000);
          if (!Number.isNaN(modified.getTime())) {
            detail.textContent = `Modified ${modified.toLocaleString()}`;
          }
        }

        meta.append(icon, title);
        card.append(meta, hint);
        if (detail.textContent) {
          card.append(detail);
        }

        card.addEventListener('click', async () => {
          setStatus('Restoring backup...', 'muted');
          card.disabled = true;
          try {
            await restoreBackup(entry.path);
            if (typeof onRestore === 'function') {
              await onRestore();
            }
            showToast('Backup loaded', 'success');
            closeModal(modal.element);
          } catch (error) {
            const message = error?.message || 'Unable to load backup';
            showToast(message, 'error');
            setStatus(message, 'error');
          } finally {
            card.disabled = false;
          }
        });

        grid.appendChild(card);
      });
  };

  const renderDirectory = async (targetPath) => {
    try {
      setStatus('Loading backups…');
      const response = await fetch(`/api/backups?path=${encodeURIComponent(targetPath)}`);
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(data.error || 'Unable to browse backups');
      }

      currentPath = data.path || targetPath;
      location.textContent = currentPath;
      up.disabled = currentPath === DEFAULT_BACKUP_DIRECTORY;
      renderEntries(data.entries || []);
    } catch (error) {
      console.error('Unable to load backup directory', error);
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

async function restoreBackup(path) {
  const response = await fetch('/api/backups/restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || 'Unable to load backup');
  }

  return data;
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
  const modal = buildModal('Preview');
  addFloatingCloseButton(modal, 'Close preview dialog');
  const message = document.createElement('p');
  message.textContent = 'Loading preview...';
  modal.content.appendChild(message);

  const previewEpisode = resolvePreviewEpisode(entry);
  const previewEpisodeOption = (entry.previewEpisodeOptions || []).find(
    (option) => option.key === previewEpisode
  );

  const requestId = (entry.previewRequestId || 0) + 1;
  entry.previewRequestId = requestId;
  entry.previewLoading = true;
  entry.previewError = null;
  updateEntryPreview(entry);

  const applyPreviewImage = (src) => {
    const img = document.createElement('img');
    img.className = 'preview-image';
    img.alt = `${entry.name} preview`;
    img.onload = () => {
      if (entry.previewRequestId !== requestId) {
        return;
      }
      markOnboardingStepComplete('preview_card');
      entry.previewSrc = src;
      entry.previewError = null;
      entry.previewLoading = false;
      updateEntryPreview(entry);
      modal.content.innerHTML = '';
      modal.content.appendChild(img);
    };
    img.onerror = () => {
      if (entry.previewRequestId !== requestId) {
        return;
      }
      entry.previewError = 'Preview unavailable';
      entry.previewLoading = false;
      updateEntryPreview(entry);
      modal.content.textContent = 'Preview unavailable';
    };
    img.src = src;
  };

  const failPreview = (error) => {
    const errorMessage = error?.message || 'Preview unavailable';
    if (entry.previewRequestId === requestId) {
      entry.previewError = errorMessage;
      entry.previewLoading = false;
      updateEntryPreview(entry);
    }
    modal.content.textContent = errorMessage;
  };

  if (!entry?.name || !entry?.config) {
    failPreview(new Error('Preview unavailable'));
    modal.footer.appendChild(closeButton(() => closeModal(modal.element)));
    return;
  }

  const payload = {
    name: entry.name,
    config: entry.config,
  };
  if (previewEpisode && previewEpisode !== 'random') {
    payload.previewEpisode = previewEpisode;
  }
  if (previewEpisodeOption) {
    if (previewEpisodeOption.season || previewEpisodeOption.season === 0) {
      payload.season = previewEpisodeOption.season;
    }
    if (previewEpisodeOption.episode || previewEpisodeOption.episode === 0) {
      payload.episode = previewEpisodeOption.episode;
    }
  }

  try {
    const response = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || 'Preview unavailable');
    }
    if (!data?.data) {
      throw new Error('Preview unavailable');
    }

    const mime = data.mime || 'image/png';
    const src = `data:${mime};base64,${data.data}`;
    if (entry.previewRequestId !== requestId) {
      return;
    }
    applyPreviewImage(src);
  } catch (error) {
    failPreview(error);
  }

  modal.footer.appendChild(closeButton(() => closeModal(modal.element)));
}

function removeEntry(entry) {
  if (!entry) {
    return;
  }

  const existingIndex = state.entries.indexOf(entry);
  if (existingIndex === -1) {
    return;
  }

  state.entries = [
    ...state.entries.slice(0, existingIndex),
    ...state.entries.slice(existingIndex + 1),
  ];
  refreshDirtyState();
  renderEntries();

  queueDestructiveAction({
    key: `remove-entry:${entry.id}`,
    label: `Removed "${entry.name}"`,
    onUndo: () => {
      state.entries = [
        ...state.entries.slice(0, existingIndex),
        entry,
        ...state.entries.slice(existingIndex),
      ];
      refreshDirtyState();
      renderEntries();
    },
    onCommit: async () => {
      state.collapsedEntries.delete(entry.id);
      state.logoBackgrounds.delete(entry.name);
      await clearLogoCacheEntry(entry);
      persistLogoBackgroundPreferences();
      refreshDirtyState();
      renderEntries();
    },
  });
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
  if (entry?.plexLookupFailed) {
    return true;
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

function clearPlexLookupFailure(entry) {
  if (entry) {
    entry.plexLookupFailed = false;
  }
}

function applyLibraryValue(entry, value) {
  if (!hasValue(value)) {
    delete entry.config.library;
    clearPlexLookupFailure(entry);
    return;
  }
  entry.config.library = value;
  clearPlexLookupFailure(entry);
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
    clearPlexLookupFailure(entry);
    return;
  }

  const numeric = Number(value);
  entry.config.rating_key = Number.isFinite(numeric) ? numeric : value;
  clearPlexLookupFailure(entry);
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

    clearPlexLookupFailure(entry);
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

  const headerActions = document.createElement('div');
  headerActions.className = 'modal-actions';

  const loadBackupButton = document.createElement('button');
  loadBackupButton.type = 'button';
  loadBackupButton.innerHTML = `
    <span class="material-symbols-rounded" aria-hidden="true">backup</span>
    <span>Load backup</span>
  `;
  loadBackupButton.addEventListener('click', () => {
    openBackupPickerModal({
      initialPath: DEFAULT_BACKUP_DIRECTORY,
      onRestore: async () => {
        await loadConfiguration();
        renderEntries();
        requestEntryPreviews(state.entries);
        closeModal(modal.element);
      },
    });
  });

  headerActions.append(loadBackupButton);
  modal.header.appendChild(headerActions);

  const tautulli = state.settings?.tautulli || {};
  const seriesSyncInterval = Number(state.settings?.series_sync_interval_seconds);
  const defaultVisibilityMode = defaultEntryVisibilityMode();
  const preferences = state.settings?.preferences || {};

  const quickActions = document.createElement('div');
  quickActions.className = 'modal-section modal-section--muted';

  const quickActionsHeader = document.createElement('div');
  quickActionsHeader.className = 'modal-section__header';
  const quickActionsTitle = document.createElement('h3');
  quickActionsTitle.textContent = 'Tools';
  const quickActionsIntro = document.createElement('p');
  quickActionsIntro.className = 'helper-text';
  quickActionsIntro.textContent = 'Open helpful dialogs from one place.';
  quickActionsHeader.append(quickActionsTitle, quickActionsIntro);

  const quickActionsButtons = document.createElement('div');
  quickActionsButtons.className = 'modal-actions';

  const unmatchedButton = document.createElement('button');
  unmatchedButton.type = 'button';
  unmatchedButton.innerHTML = `
    <span class="material-symbols-rounded" aria-hidden="true">warning</span>
    <span>Unmatched</span>
  `;
  unmatchedButton.addEventListener('click', () => {
    closeModal(modal.element);
    openUnmatchedItemsModal();
  });

  const recentsButton = document.createElement('button');
  recentsButton.type = 'button';
  recentsButton.innerHTML = `
    <span class="material-symbols-rounded" aria-hidden="true">history</span>
    <span>Recents</span>
  `;
  recentsButton.addEventListener('click', () => {
    closeModal(modal.element);
    openRecentsModal();
  });

  const convertLegacyButton = document.createElement('button');
  convertLegacyButton.type = 'button';
  convertLegacyButton.innerHTML = `
    <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
    <span>Convert legacy tv.yml</span>
  `;
  convertLegacyButton.addEventListener('click', async () => {
    convertLegacyButton.disabled = true;
    status.textContent = 'Converting legacy tv.yml keys...';

    try {
      const result = await convertLegacyTvYaml();
      await loadConfiguration();
      renderEntries();
      showToast('Converted tv.yml to canonical keys');

      const updatedSeries = Number(result?.updatedSeries || 0);
      const backupPath = result?.backupPath || 'tv-backup.yml';
      status.textContent = `Converted ${updatedSeries} series. Backup saved to ${backupPath}.`;
    } catch (error) {
      const message = error?.message || 'Unable to convert tv.yml';
      status.textContent = message;
      showToast(message, 'error');
    } finally {
      convertLegacyButton.disabled = false;
    }
  });

  const commandPaletteButton = document.createElement('button');
  commandPaletteButton.type = 'button';
  commandPaletteButton.innerHTML = `
    <span class="material-symbols-rounded" aria-hidden="true">keyboard_command_key</span>
    <span>Command palette</span>
  `;
  commandPaletteButton.addEventListener('click', () => openCommandPaletteModal());

  quickActionsButtons.append(
    unmatchedButton,
    recentsButton,
    convertLegacyButton,
    commandPaletteButton,
  );
  quickActions.append(quickActionsHeader, quickActionsButtons);

  const shortcutsSection = document.createElement('div');
  shortcutsSection.className = 'modal-section modal-section--muted';
  const shortcutsHeader = document.createElement('div');
  shortcutsHeader.className = 'modal-section__header';
  const shortcutsTitle = document.createElement('h3');
  shortcutsTitle.textContent = 'Keyboard shortcuts';
  const shortcutsIntro = document.createElement('p');
  shortcutsIntro.className = 'helper-text';
  shortcutsIntro.textContent = 'Shortcuts are disabled while typing in text fields.';
  shortcutsHeader.append(shortcutsTitle, shortcutsIntro);

  const shortcutsList = document.createElement('ul');
  shortcutsList.className = 'helper-text';
  commandDefinitions().forEach((command) => {
    const item = document.createElement('li');
    item.textContent = `${command.label}: ${command.shortcuts.join(' or ')}`;
    shortcutsList.appendChild(item);
  });
  shortcutsSection.append(shortcutsHeader, shortcutsList);

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

  const userStatus = document.createElement('div');
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


  const visibilityField = document.createElement('label');
  visibilityField.className = 'modal-controls__field';
  const visibilityLabelText = document.createElement('span');
  visibilityLabelText.className = 'modal-controls__label';
  visibilityLabelText.textContent = 'Default entry field mode';
  const visibilitySelect = document.createElement('select');
  visibilitySelect.className = 'modal-select';
  const basicVisibility = document.createElement('option');
  basicVisibility.value = 'basic';
  basicVisibility.textContent = 'Basic';
  const advancedVisibility = document.createElement('option');
  advancedVisibility.value = 'advanced';
  advancedVisibility.textContent = 'Advanced';
  visibilitySelect.append(basicVisibility, advancedVisibility);
  visibilitySelect.value = defaultVisibilityMode;
  visibilityField.append(visibilityLabelText, visibilitySelect);
  syncControls.append(visibilityField);
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
  const filteredPreferencesKeys = preferencesKeys.filter(
    (key) => key !== 'tautulli' && key !== 'webui',
  );
  if (filteredPreferencesKeys.length) {
    filteredPreferencesKeys.forEach((key) => {
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
      const selectedVisibilityMode = normalizeEntryVisibilityMode(visibilitySelect.value);
      await saveSettings({
        series_sync_interval_seconds: syncIntervalSeconds,
        entry_visibility_default_mode: selectedVisibilityMode,
        tautulli: {
          url: urlInput.value,
          api_key: keyInput.value,
          user_id: userSelect.value,
          verify_ssl: verifyInput.checked,
        },
        preferences: buildPreferencePayload(preferences),
      });
      state.entries.forEach((existingEntry) => {
        if (!existingEntry || !existingEntry.visibilityMode) {
          return;
        }
        if (!ENTRY_VISIBILITY_MODES.has(existingEntry.visibilityMode)) {
          existingEntry.visibilityMode = selectedVisibilityMode;
        }
      });
      renderEntries();
      status.textContent = 'Settings saved.';
      showToast('Settings updated');
      await refreshConnectionStatusLights();
    } catch (error) {
      const failedToPersist = error && error.didPersist === true;
      if (failedToPersist) {
        status.textContent = `⚠ Save failed to persist: ${error.message}`;
        showToast(`⚠ Save failed to persist: ${error.message}`, 'error-critical');
      } else {
        status.textContent = error.message;
        showToast(error.message, 'error');
      }
    } finally {
      saveButton.disabled = false;
    }
  });

  const loadUsers = async () => {
    userSelect.disabled = true;
    userStatus.replaceChildren();
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
      if (users.length) {
        userStatus.replaceChildren();
        userStatus.textContent = 'Select a Plex user to filter watch history.';
      } else {
        const emptyUsers = createActionableEmptyState({
          title: 'No Tautulli users returned',
          message:
            'Check API key and URL, then reload users. Confirm Tautulli can reach your Plex server.',
          primaryLabel: 'Reload users',
          primaryAction: loadUsers,
          secondaryLabel: 'Tautulli help',
          secondaryHref: HELP_LINKS.tautulliSetup,
          compact: true,
        });
        userStatus.replaceChildren(emptyUsers);
      }
    } catch (error) {
      const userError = createActionableEmptyState({
        title: 'Unable to load Tautulli users',
        message: `${error.message}. Check API key and URL, then retry.`,
        primaryLabel: 'Retry user load',
        primaryAction: loadUsers,
        secondaryLabel: 'Tautulli help',
        secondaryHref: HELP_LINKS.tautulliSetup,
        compact: true,
      });
      userStatus.replaceChildren(userError);
    } finally {
      userSelect.disabled = false;
    }
  };

  loadUsers();

  tautulliControls.append(urlField, keyField, userField, verifyField);
  tautulliSection.append(tautulliHeader, tautulliControls, userStatus);
  preferencesSection.prepend(preferencesHeader);

  modal.content.append(quickActions, shortcutsSection, tautulliSection, syncSection, preferencesSection, status);
  modal.footer.append(saveButton, closeButton(() => closeModal(modal.element)));
}

function maybeOpenPreferenceWizard() {
  if (!state.settings?.preference_setup_required) {
    return;
  }

  openPreferenceWizardModal();
}

function openPreferenceWizardModal() {
  const modal = buildModal('Initial preferences setup');

  const helper = document.createElement('p');
  helper.className = 'helper-text';
  helper.textContent =
    'Complete these required preferences before using the rest of the app.';
  modal.content.appendChild(helper);

  const preferences = state.settings?.preferences || {};
  const options = preferences.options && typeof preferences.options === 'object'
    ? preferences.options
    : {};

  const form = document.createElement('div');
  form.className = 'modal-controls';

  const sourceField = document.createElement('label');
  sourceField.className = 'modal-controls__field';
  const sourceLabel = document.createElement('span');
  sourceLabel.className = 'modal-controls__label';
  sourceLabel.textContent = 'Source directory';
  const sourceInput = document.createElement('input');
  sourceInput.type = 'text';
  sourceInput.value = options.source || '/config/source/';
  const sourceHint = document.createElement('p');
  sourceHint.className = 'helper-text preference-wizard__hint';
  sourceHint.textContent =
    'Path to source assets. Docker example: /config/source/. Local example: ./source/';
  const sourceValidation = document.createElement('p');
  sourceValidation.className = 'helper-text preference-wizard__validation';
  sourceValidation.hidden = true;
  sourceField.append(sourceLabel, sourceInput, sourceHint, sourceValidation);

  const seriesField = document.createElement('label');
  seriesField.className = 'modal-controls__field';
  const seriesLabel = document.createElement('span');
  seriesLabel.className = 'modal-controls__label';
  seriesLabel.textContent = 'Series YAML path';
  const seriesInput = document.createElement('input');
  seriesInput.type = 'text';
  seriesInput.value = options.series || '/config/tv.yml';
  const seriesHint = document.createElement('p');
  seriesHint.className = 'helper-text preference-wizard__hint';
  seriesHint.textContent =
    'Path to tv.yml file. Docker example: /config/tv.yml. Local example: ./config/tv.yml';
  const seriesValidation = document.createElement('p');
  seriesValidation.className = 'helper-text preference-wizard__validation';
  seriesValidation.hidden = true;
  seriesField.append(seriesLabel, seriesInput, seriesHint, seriesValidation);

  form.append(sourceField, seriesField);
  modal.content.appendChild(form);

  const status = document.createElement('p');
  status.className = 'helper-text preference-wizard__status';
  modal.content.appendChild(status);

  const normalizePathInput = (value) => (value || '').toString();

  const validatePathField = (rawValue, fieldType) => {
    const value = normalizePathInput(rawValue);
    const trimmed = value.trim();
    const errors = [];

    if (!trimmed) {
      errors.push('This field is required.');
      return errors;
    }

    if (value !== trimmed) {
      errors.push('Remove leading/trailing spaces from this path.');
    }

    if (/\s{2,}/.test(trimmed)) {
      errors.push('Avoid repeated spaces in file paths.');
    }

    if (/[\r\n\t]/.test(trimmed)) {
      errors.push('Path cannot include tabs or new lines.');
    }

    if (trimmed.includes('://')) {
      errors.push('Use a filesystem path, not a URL.');
    }

    if (/[<>|*"']/g.test(trimmed)) {
      errors.push('Path contains characters that are usually invalid on filesystems.');
    }

    if (!trimmed.startsWith('/') && !trimmed.startsWith('./')) {
      errors.push('Use an absolute path (/...) or a local relative path (./...).');
    }

    if (fieldType === 'series' && !/\.(ya?ml)$/i.test(trimmed)) {
      errors.push('Series path should point to a .yml or .yaml file.');
    }

    return errors;
  };

  const setFieldValidationState = (input, validationNode, errors) => {
    if (errors.length === 0) {
      input.classList.remove('preference-wizard__input-error');
      validationNode.hidden = true;
      validationNode.textContent = '';
      return;
    }

    input.classList.add('preference-wizard__input-error');
    validationNode.hidden = false;
    validationNode.textContent = errors[0];
  };

  const runClientValidation = () => {
    const sourceErrors = validatePathField(sourceInput.value, 'source');
    const seriesErrors = validatePathField(seriesInput.value, 'series');

    setFieldValidationState(sourceInput, sourceValidation, sourceErrors);
    setFieldValidationState(seriesInput, seriesValidation, seriesErrors);
    saveButton.disabled = sourceErrors.length > 0 || seriesErrors.length > 0;

    return {
      sourceErrors,
      seriesErrors,
      valid: sourceErrors.length === 0 && seriesErrors.length === 0,
    };
  };

  const renderServerValidation = (result) => {
    const sourceMessages = Array.isArray(result?.fields?.source?.messages)
      ? result.fields.source.messages
      : [];
    const seriesMessages = Array.isArray(result?.fields?.series?.messages)
      ? result.fields.series.messages
      : [];

    setFieldValidationState(sourceInput, sourceValidation, sourceMessages);
    setFieldValidationState(seriesInput, seriesValidation, seriesMessages);

    const generalMessages = Array.isArray(result?.messages) ? result.messages : [];
    if (generalMessages.length) {
      status.textContent = generalMessages.join(' ');
    } else if (result?.valid) {
      status.textContent = 'Paths validated. Saving preferences...';
    } else {
      status.textContent = 'Please resolve the highlighted path issues and try again.';
    }
  };

  sourceInput.addEventListener('input', () => {
    status.textContent = '';
    runClientValidation();
  });
  seriesInput.addEventListener('input', () => {
    status.textContent = '';
    runClientValidation();
  });

  const saveButton = document.createElement('button');
  saveButton.type = 'button';
  saveButton.textContent = 'Save and continue';
  saveButton.addEventListener('click', async () => {
    const clientValidation = runClientValidation();
    if (!clientValidation.valid) {
      status.textContent = 'Fix the highlighted fields before saving.';
      return;
    }

    const source = sourceInput.value.trim();
    const series = seriesInput.value.trim();

    saveButton.disabled = true;
    status.textContent = 'Validating paths...';

    try {
      const validationResponse = await fetch('/api/validate/preferences-paths', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, series }),
      });

      const validationPayload = await validationResponse.json().catch(() => ({}));
      if (!validationResponse.ok || validationPayload.valid !== true) {
        renderServerValidation(validationPayload);
        return;
      }

      await saveSettings({
        preferences: {
          options: {
            source,
            series,
          },
          webui: {
            setup_complete: true,
          },
        },
      });
      state.settings.preference_setup_required = false;
      status.textContent = 'Preferences saved.';
      showToast('Preferences saved');
      markOnboardingStepComplete('set_preferences');
      closeModal(modal.element);
      await loadConfiguration();
      renderEntries();
      requestEntryPreviews(state.entries);
    } catch (error) {
      status.textContent = error.message || 'Unable to save preferences';
      showToast(status.textContent, 'error');
    } finally {
      if (!state.settings?.preference_setup_required) {
        return;
      }
      runClientValidation();
    }
  });

  modal.footer.appendChild(saveButton);
  runClientValidation();
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
    markOnboardingStepComplete('add_first_series');
    setEntryCollapsed(newEntry.id, false);
    state.pendingEntryId = newEntry.id;
    sortEntries();
    refreshDirtyState();

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

function stableStringify(value) {
  const seen = new WeakSet();

  const normalize = (input) => {
    if (input === null || typeof input !== 'object') {
      return input;
    }
    if (seen.has(input)) {
      return null;
    }
    seen.add(input);

    if (Array.isArray(input)) {
      return input.map(normalize);
    }

    return Object.keys(input)
      .sort()
      .reduce((result, key) => {
        result[key] = normalize(input[key]);
        return result;
      }, {});
  };

  return JSON.stringify(normalize(value));
}

function normalizeSnapshot(snapshot) {
  if (snapshot === null || snapshot === undefined) {
    return null;
  }
  try {
    const parsed = typeof snapshot === 'string' ? JSON.parse(snapshot) : snapshot;
    return stableStringify(parsed);
  } catch (error) {
    try {
      return stableStringify(snapshot);
    } catch (stringifyError) {
      console.warn('Failed to normalize snapshot', stringifyError);
      return typeof snapshot === 'string' ? snapshot : null;
    }
  }
}

function snapshotEntry(entry) {
  const previewEpisode = resolvePreviewEpisode(entry);
  const config = cloneData(entry.config) || {};

  if (config && typeof config === 'object' && !Array.isArray(config)) {
    delete config.previewEpisode;
    delete config.preview_episode;
  }

  return {
    name: entry.name,
    config,
    previewEpisode: previewEpisode || 'random',
  };
}

function normalizePersistedPayload(rawPayload) {
  const payload = rawPayload && typeof rawPayload === 'object' ? rawPayload : {};
  const libraries = cloneData(payload.libraries) || {};
  const series = Array.isArray(payload.series) ? payload.series : [];
  const normalizedSeries = series
    .map((entry) => ({
      name: String(entry?.name || ''),
      config: cloneData(entry?.config) || {},
    }))
    .filter((entry) => entry.name.length > 0)
    .map((entry) => snapshotEntry(entry))
    .map((entry) => ({
      name: entry.name,
      config: entry.config,
    }))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));

  return {
    libraries,
    series: normalizedSeries,
  };
}

function baselineFingerprintFromPayload(payload) {
  return hashString(stableStringify(normalizePersistedPayload(payload)));
}

function buildCurrentNormalizedPayload() {
  return normalizePersistedPayload({
    libraries: state.libraries,
    series: state.entries.map((entry) => ({
      name: entry.name,
      config: entry.config,
    })),
  });
}

function persistedEntryOrderFromPayload(payload) {
  const normalized = normalizePersistedPayload(payload);
  return normalized.series.map((entry, index) => `${index}:${entry.name}`);
}

function assignPersistedBaseline(payload, fingerprint = null) {
  const normalizedPayload = normalizePersistedPayload(payload);
  state.persistedBaselinePayload = normalizedPayload;
  state.persistedBaselineEntryOrder = persistedEntryOrderFromPayload(normalizedPayload);
  state.persistedBaselineFingerprint = baselineFingerprintFromPayload(normalizedPayload);
  state.persistedServerFingerprint =
    typeof fingerprint === 'string' && fingerprint.trim().length > 0
      ? fingerprint.trim()
      : state.persistedBaselineFingerprint;
}

function currentEntryOrderForDirtyCheck() {
  const normalizedPayload = buildCurrentNormalizedPayload();
  return persistedEntryOrderFromPayload(normalizedPayload);
}

function computeDirtyState() {
  if (!state.persistedBaselinePayload) {
    return state.entries.length > 0;
  }

  const currentOrder = currentEntryOrderForDirtyCheck();
  if (state.persistedBaselineEntryOrder.length !== currentOrder.length) {
    return true;
  }

  if (state.persistedBaselineEntryOrder.some((id, index) => id !== currentOrder[index])) {
    return true;
  }

  const currentPayload = buildCurrentNormalizedPayload();
  const currentFingerprint = baselineFingerprintFromPayload(currentPayload);
  return currentFingerprint !== state.persistedBaselineFingerprint;
}

function setDirtyState(isDirty) {
  state.isDirty = Boolean(isDirty);
  if (dom.dirtyIndicator) {
    dom.dirtyIndicator.hidden = !state.isDirty;
  }
  if (dom.runBuilder) {
    dom.runBuilder.disabled = state.isDirty;
    dom.runBuilder.title = state.isDirty
      ? 'Save configuration before building.'
      : '';
  }
}

function refreshDirtyState() {
  setDirtyState(computeDirtyState());
}

let cacheDbPromise = null;
let cacheDbUnavailable = false;
let cacheDbWarningShown = false;

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
    let settled = false;

    const resolveSafely = (value) => {
      if (settled) {
        return;
      }
      settled = true;
      resolve(value);
    };

    const notifyCacheDbUnavailable = (message, error = null) => {
      cacheDbUnavailable = true;
      if (error) {
        console.warn(message, error);
      } else {
        console.warn(message);
      }
      if (!cacheDbWarningShown) {
        showToast('Image caching is disabled (browser storage unavailable).', 'warning');
        cacheDbWarningShown = true;
      }
    };

    const timeoutId = setTimeout(() => {
      notifyCacheDbUnavailable('Timed out while opening cache database');
      resolveSafely(null);
    }, CACHE_DB_OPEN_TIMEOUT_MS);

    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(LOGO_DB_STORE)) {
        db.createObjectStore(LOGO_DB_STORE, { keyPath: 'key' });
      }
    };

    request.onsuccess = () => {
      clearTimeout(timeoutId);
      resolveSafely(request.result);
    };

    request.onerror = () => {
      clearTimeout(timeoutId);
      notifyCacheDbUnavailable('Failed to open cache database', request.error);
      resolveSafely(null);
    };

    request.onblocked = () => {
      clearTimeout(timeoutId);
      notifyCacheDbUnavailable('Cache database open request is blocked');
      resolveSafely(null);
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

function hashString(value) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return hash.toString(16);
}

function setSaveButtonState(isSaving) {
  if (!dom.save) {
    return;
  }

  saveInProgress = isSaving;
  updateSaveButtonDisabledState();
  const label = dom.save.querySelector('.button-label');
  if (label) {
    label.textContent = isSaving ? 'Saving...' : 'Save';
  }
}

function formatSaveTimestamp(timestamp) {
  const resolved =
    Number.isFinite(Number(timestamp)) && Number(timestamp) > 0
      ? new Date(Number(timestamp) * 1000)
      : new Date();
  return resolved.toLocaleString();
}

function normalizeSaveDetails(details, fallbackEntryCount) {
  const payload = details && typeof details === 'object' ? details : {};
  const failedEntries = Array.isArray(payload.failed_entries) ? payload.failed_entries : [];
  const validationWarnings = Array.isArray(payload.validation_warnings)
    ? payload.validation_warnings
    : [];
  const fieldValidationWarnings = Array.isArray(payload.field_validation_warnings)
    ? payload.field_validation_warnings
    : [];
  const validationErrors = Array.isArray(payload.validation_errors) ? payload.validation_errors : [];
  const requestedEntriesCount = Number.isFinite(Number(payload.requested_entries_count))
    ? Number(payload.requested_entries_count)
    : fallbackEntryCount;
  const savedEntriesCount = Number.isFinite(Number(payload.saved_entries_count))
    ? Number(payload.saved_entries_count)
    : Math.max(requestedEntriesCount - failedEntries.length, 0);
  const timestamp = Number.isFinite(Number(payload.saved_at))
    ? Number(payload.saved_at)
    : Date.now() / 1000;

  return {
    timestamp,
    requestedEntriesCount,
    savedEntriesCount,
    validationWarnings: [...validationWarnings, ...fieldValidationWarnings.map((item) => item.message)],
    validationErrors,
    failedEntries,
    hasWarnings:
      payload.has_warnings === true ||
      validationWarnings.length > 0 ||
      fieldValidationWarnings.length > 0,
    hasErrors: payload.has_errors === true || validationErrors.length > 0,
    hasFailures:
      payload.has_failures === true || failedEntries.length > 0 || validationErrors.length > 0,
  };
}

function summarizeSave(details) {
  const warningCount = details.validationWarnings.length;
  const failureCount = details.failedEntries.length;
  if (failureCount > 0) {
    return `Saved ${details.savedEntriesCount}/${details.requestedEntriesCount} entries • ${failureCount} failed • ${warningCount} warning${warningCount === 1 ? '' : 's'}`;
  }
  if (warningCount > 0) {
    return `Saved ${details.savedEntriesCount} entries with ${warningCount} warning${warningCount === 1 ? '' : 's'}`;
  }
  return `Saved ${details.savedEntriesCount} entries successfully`;
}

function dismissSaveStatusPanel() {
  if (saveStatusPanel) {
    saveStatusPanel.remove();
    saveStatusPanel = null;
  }
}

function renderSaveStatusPanel(result, { archiveCurrent = false } = {}) {
  if (!dom.header) {
    return;
  }

  if (archiveCurrent && saveStatusPanel?.dataset?.statusSummary) {
    saveStatusArchive.unshift({
      summary: saveStatusPanel.dataset.statusSummary,
      timestamp: saveStatusPanel.dataset.statusTimestamp || '',
    });
    saveStatusArchive = saveStatusArchive.slice(0, 5);
  }

  dismissSaveStatusPanel();

  const panel = document.createElement('section');
  panel.className = `save-status-panel save-status-panel--${result.type || 'info'}`;
  panel.setAttribute('role', 'status');
  panel.dataset.statusSummary = result.summary || '';
  panel.dataset.statusTimestamp = result.timestampLabel || '';

  const topRow = document.createElement('div');
  topRow.className = 'save-status-panel__top';

  const title = document.createElement('strong');
  title.className = 'save-status-panel__title';
  title.textContent = result.title || 'Save status';

  const dismissButton = document.createElement('button');
  dismissButton.type = 'button';
  dismissButton.className = 'save-status-panel__dismiss';
  dismissButton.setAttribute('aria-label', 'Dismiss save status');
  dismissButton.textContent = 'Dismiss';
  dismissButton.addEventListener('click', dismissSaveStatusPanel);
  topRow.append(title, dismissButton);

  const timestampLine = document.createElement('p');
  timestampLine.className = 'save-status-panel__timestamp';
  timestampLine.textContent = result.timestampLabel || '';

  const summary = document.createElement('p');
  summary.className = 'save-status-panel__summary';
  summary.textContent = result.summary || '';

  const details = document.createElement('details');
  details.className = 'save-status-panel__details';
  const detailsSummary = document.createElement('summary');
  detailsSummary.textContent = 'Details';
  details.appendChild(detailsSummary);

  const list = document.createElement('ul');
  list.className = 'save-status-panel__list';
  (result.detailLines || []).forEach((line) => {
    const item = document.createElement('li');
    item.textContent = line;
    list.appendChild(item);
  });
  details.appendChild(list);

  if (saveStatusArchive.length > 0) {
    const archive = document.createElement('details');
    archive.className = 'save-status-panel__archive';
    const archiveSummary = document.createElement('summary');
    archiveSummary.textContent = `Recent save history (${saveStatusArchive.length})`;
    archive.appendChild(archiveSummary);
    const archiveList = document.createElement('ul');
    archiveList.className = 'save-status-panel__list';
    saveStatusArchive.forEach((entry) => {
      const item = document.createElement('li');
      item.textContent = `${entry.timestamp}: ${entry.summary}`;
      archiveList.appendChild(item);
    });
    archive.appendChild(archiveList);
    panel.append(topRow, timestampLine, summary, details, archive);
  } else {
    panel.append(topRow, timestampLine, summary, details);
  }

  dom.header.insertAdjacentElement('afterend', panel);
  saveStatusPanel = panel;
}

async function saveConfiguration() {
  if (saveInProgress) {
    showToast('Save already in progress...', 'info');
    return;
  }
  if (hasHardValidationErrors()) {
    showToast('Resolve validation errors before saving.', 'error');
    return;
  }

  setSaveButtonState(true);
  const savingToast = showToast('Saving configuration...', 'info');

  try {
    sortEntries();
    renderEntries();
    state.entries.forEach((entry) => syncPreviewEpisodeConfig(entry));
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
      if (data?.details) {
        const details = normalizeSaveDetails(data.details, state.entries.length);
        const validationLines = (details.validationErrors || []).map((issue) => {
          const name = issue?.name || `Entry #${(issue?.index ?? 0) + 1}`;
          const field = issue?.field ? `${issue.field}: ` : '';
          return `Validation error (${name}) ${field}${issue?.message || 'Invalid value.'}`;
        });
        if (validationLines.length > 0) {
          renderSaveStatusPanel({
            type: 'error',
            title: 'Save failed',
            timestampLabel: formatSaveTimestamp(Date.now() / 1000),
            summary: data.error || 'Configuration validation failed.',
            detailLines: validationLines,
          });
          throw new Error(data.error || validationLines[0]);
        }
      }
      throw new Error(data.error || 'Failed to save configuration');
    }

    const data = await response.json().catch(() => ({}));
    const details = normalizeSaveDetails(data?.details, state.entries.length);
    const summary = summarizeSave(details);
    const timestampLabel = formatSaveTimestamp(details.timestamp);
    const detailLines = [
      `Requested entries: ${details.requestedEntriesCount}`,
      `Saved entries: ${details.savedEntriesCount}`,
      `Warnings: ${details.validationWarnings.length}`,
      `Failed entries: ${details.failedEntries.length}`,
      ...details.validationWarnings.map((warning) => `Warning: ${warning}`),
      ...details.failedEntries.map((entry, index) => {
        const label = entry?.name ? `${entry.name}` : `Entry #${(entry?.index ?? index) + 1}`;
        const reason = entry?.reason || 'Unknown failure';
        return `Failed ${label}: ${reason}`;
      }),
    ];

    renderSaveStatusPanel(
      {
        type: details.hasFailures ? 'error' : details.hasWarnings ? 'warning' : 'success',
        title: details.hasFailures ? 'Saved with failures' : 'Configuration saved',
        timestampLabel,
        summary,
        detailLines,
      },
      { archiveCurrent: details.hasFailures === false }
    );

    showToast(
      details.hasFailures ? 'Configuration saved with issues' : 'Configuration saved',
      details.hasFailures ? 'error' : details.hasWarnings ? 'info' : 'success'
    );
    markOnboardingStepComplete('save_config');

    await loadConfiguration();
    renderEntries();
  } catch (error) {
    const message = error?.message || 'Unable to save configuration';
    renderSaveStatusPanel({
      type: 'error',
      title: 'Save failed',
      timestampLabel: formatSaveTimestamp(Date.now() / 1000),
      summary: message,
      detailLines: ['The configuration was not persisted. Review the error and try again.'],
    });
    showToast(message, 'error');
  } finally {
    setSaveButtonState(false);
    if (savingToast) {
      savingToast.remove();
    }
  }
}

window.addEventListener('beforeunload', (event) => {
  stopPersistedFingerprintPolling();
  if (!state.isDirty) {
    return;
  }
  event.preventDefault();
  event.returnValue = '';
});

function sortEntries() {
  state.entries.sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
  );
}

// -----------------------------------------------------------------------------
// Modal helpers
// -----------------------------------------------------------------------------
function buildModal(title) {
  const previouslyFocused =
    document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';

  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.tabIndex = -1;

  const header = document.createElement('header');
  const heading = document.createElement('h2');
  heading.id = `modal-title-${++modalIdCounter}`;
  heading.textContent = title;
  modal.setAttribute('aria-labelledby', heading.id);
  header.appendChild(heading);

  const content = document.createElement('div');
  const footer = document.createElement('footer');

  modal.append(header, content, footer);
  backdrop.appendChild(modal);
  dom.modals.appendChild(backdrop);

  const modalParts = { element: backdrop, modal, header, content, footer };
  addFloatingCloseButton(modalParts, 'Close dialog');

  const context = {
    element: backdrop,
    modal,
    previouslyFocused,
    dismissible: true,
  };
  activeModalStack.push(context);
  requestAnimationFrame(() => {
    focusFirstModalElement(modal);
  });

  return modalParts;
}

function addFloatingCloseButton(modal, label = 'Close dialog') {
  const existingButton = modal.modal.querySelector('.modal-close--floating');
  if (existingButton) {
    existingButton.setAttribute('aria-label', label);
    return existingButton;
  }
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
  button.type = 'button';
  button.textContent = 'Close';
  button.addEventListener('click', onClick);
  return button;
}

function closeModal(element) {
  hideCardTypePreview();
  const modalIndex = activeModalStack.findIndex((context) => context.element === element);
  const isTopModal = modalIndex === activeModalStack.length - 1;
  const [closedContext] = modalIndex >= 0 ? activeModalStack.splice(modalIndex, 1) : [];
  element.remove();
  if (!isTopModal) {
    return;
  }

  const nextContext = activeModalStack[activeModalStack.length - 1];
  if (nextContext) {
    focusFirstModalElement(nextContext.modal);
    return;
  }

  if (closedContext?.previouslyFocused && document.contains(closedContext.previouslyFocused)) {
    closedContext.previouslyFocused.focus({ preventScroll: true });
  }
}

function getFocusableModalElements(modalElement) {
  if (!modalElement) {
    return [];
  }
  return [...modalElement.querySelectorAll(MODAL_FOCUSABLE_SELECTOR)].filter(
    (element) =>
      element instanceof HTMLElement &&
      !element.hasAttribute('disabled') &&
      !element.getAttribute('aria-hidden') &&
      element.getClientRects().length > 0
  );
}

function focusFirstModalElement(modalElement) {
  const focusable = getFocusableModalElements(modalElement);
  if (focusable.length > 0) {
    focusable[0].focus({ preventScroll: true });
    return;
  }
  modalElement.focus({ preventScroll: true });
}

function trapModalFocus(event) {
  const activeContext = activeModalStack[activeModalStack.length - 1];
  if (!activeContext) {
    return;
  }

  if (event.key === 'Escape' && activeContext.dismissible) {
    event.preventDefault();
    closeModal(activeContext.element);
    return;
  }

  if (event.key !== 'Tab') {
    return;
  }

  const focusable = getFocusableModalElements(activeContext.modal);
  if (focusable.length === 0) {
    event.preventDefault();
    activeContext.modal.focus({ preventScroll: true });
    return;
  }

  const firstFocusable = focusable[0];
  const lastFocusable = focusable[focusable.length - 1];
  const activeElement = document.activeElement;
  const activeInsideModal =
    activeElement instanceof HTMLElement && activeContext.modal.contains(activeElement);

  if (!activeInsideModal) {
    event.preventDefault();
    (event.shiftKey ? lastFocusable : firstFocusable).focus({ preventScroll: true });
    return;
  }

  if (event.shiftKey && activeElement === firstFocusable) {
    event.preventDefault();
    lastFocusable.focus({ preventScroll: true });
    return;
  }

  if (!event.shiftKey && activeElement === lastFocusable) {
    event.preventDefault();
    firstFocusable.focus({ preventScroll: true });
  }
}

document.addEventListener('keydown', trapModalFocus, true);

// -----------------------------------------------------------------------------
// Toast notifications
// -----------------------------------------------------------------------------
function showToast(message, type = 'info', options = {}) {
  const { duration = 4500, actionLabel = '', onAction, actions = [] } = options;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const messageElement = document.createElement('span');
  messageElement.className = 'toast__message';
  messageElement.textContent = message || '';
  toast.appendChild(messageElement);

  if (actionLabel && typeof onAction === 'function') {
    const actionButton = document.createElement('button');
    actionButton.type = 'button';
    actionButton.className = 'toast__action';
    actionButton.textContent = actionLabel;
    actionButton.addEventListener('click', () => onAction());
    toast.appendChild(actionButton);
  }

  if (Array.isArray(actions)) {
    actions.forEach((action) => {
      if (!action?.label || typeof action.onClick !== 'function') {
        return;
      }
      const extraActionButton = document.createElement('button');
      extraActionButton.type = 'button';
      extraActionButton.className = 'toast__action';
      extraActionButton.textContent = action.label;
      extraActionButton.addEventListener('click', () => action.onClick());
      toast.appendChild(extraActionButton);
    });
  }

  toastContainer.appendChild(toast);
  if (String(type || '').startsWith('error')) {
    showErrorAssistToast(message);
  }
  if (duration > 0) {
    setTimeout(() => toast.remove(), duration);
  }
  return toast;
}

function lookupErrorAssist(message) {
  const text = String(message || '').toLowerCase();
  if (!text) {
    return null;
  }
  return (
    ERROR_ASSIST_RULES.find((rule) => {
      if (!Array.isArray(rule.signatureAny)) {
        return false;
      }
      return rule.signatureAny.some((token) => text.includes(token));
    }) || null
  );
}

function showErrorAssistToast(message) {
  const assist = lookupErrorAssist(message);
  if (!assist) {
    return;
  }
  const compactSteps = Array.isArray(assist.steps) ? assist.steps.map((step) => `• ${step}`).join(' ') : '';
  const guidanceMessage = `${assist.title}. ${compactSteps}`.trim();
  const actions = [];
  if (assist.readmeLink) {
    actions.push({
      label: 'README',
      onClick: () => window.open(assist.readmeLink, '_blank', 'noopener,noreferrer'),
    });
  }
  if (assist.settingsLabel && typeof assist.settingsAction === 'function') {
    actions.push({
      label: assist.settingsLabel,
      onClick: () => assist.settingsAction(),
    });
  }
  showToast(`How to fix: ${guidanceMessage}`, 'info', { duration: 12000, actions });
}

function queueDestructiveAction({
  key,
  label,
  undoLabel = 'Undo',
  undoWindowMs = DESTRUCTIVE_ACTION_UNDO_WINDOW_MS,
  onCommit,
  onUndo,
}) {
  if (!key || typeof onCommit !== 'function') {
    return false;
  }
  if (pendingDestructiveActions.has(key)) {
    showToast('Action already queued. Use Undo from the existing toast to cancel.', 'info');
    return false;
  }

  const pending = {
    key,
    committed: false,
    canceled: false,
    timerId: null,
    toast: null,
  };

  const clearPending = () => {
    if (pending.timerId) {
      clearTimeout(pending.timerId);
      pending.timerId = null;
    }
    if (pending.toast) {
      pending.toast.remove();
      pending.toast = null;
    }
    pendingDestructiveActions.delete(key);
  };

  const undo = () => {
    if (!pendingDestructiveActions.has(key) || pending.committed) {
      return;
    }
    pending.canceled = true;
    clearPending();
    if (typeof onUndo === 'function') {
      onUndo();
    }
    showToast(`${label} canceled.`, 'info');
  };

  pending.toast = showToast(`${label}.`, 'info', {
    duration: undoWindowMs,
    actionLabel: undoLabel,
    onAction: undo,
  });

  pending.timerId = setTimeout(async () => {
    if (pending.canceled) {
      return;
    }
    pending.committed = true;
    clearPending();
    try {
      await onCommit();
    } catch (error) {
      console.error('Failed to finalize destructive action', { key, error });
      showToast(error?.message || 'Unable to complete action.', 'error');
    }
  }, undoWindowMs);

  pendingDestructiveActions.set(key, pending);
  return true;
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
