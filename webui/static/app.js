const state = {
  libraries: {},
  entries: [],
  fields: [],
  fontDirectory: '/config/fonts',
  filter: '',
};

const dom = {
  entries: document.getElementById('entries'),
  search: document.getElementById('series-search'),
  addEntry: document.getElementById('add-entry'),
  save: document.getElementById('save-config'),
  modals: document.getElementById('modals'),
};

const toastContainer = document.createElement('div');
toastContainer.className = 'toast-container';
document.body.appendChild(toastContainer);

// -----------------------------------------------------------------------------
// Initialization
// -----------------------------------------------------------------------------
async function init() {
  try {
    await loadMetadata();
    await loadConfiguration();
    registerEvents();
    renderEntries();
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
}

function registerEvents() {
  dom.search.addEventListener('input', (event) => {
    state.filter = event.target.value.toLowerCase();
    renderEntries();
  });

  dom.addEntry.addEventListener('click', () => openAddEntryModal());

  dom.save.addEventListener('click', () => saveConfiguration());
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

  filtered.forEach((entry) => {
    dom.entries.appendChild(renderEntry(entry));
  });
}

function renderEntry(entry) {
  const container = document.createElement('article');
  container.className = 'entry';

  const header = document.createElement('div');
  header.className = 'entry-header';

  const titleInput = document.createElement('input');
  titleInput.type = 'text';
  titleInput.value = entry.name;
  titleInput.addEventListener('input', (event) => {
    entry.name = event.target.value;
  });

  const actions = document.createElement('div');
  actions.className = 'entry-actions';

  const previewButton = document.createElement('button');
  previewButton.textContent = 'Preview';
  previewButton.addEventListener('click', () => openPreview(entry));

  const deleteButton = document.createElement('button');
  deleteButton.textContent = 'Remove';
  deleteButton.style.background = 'rgba(227, 107, 107, 0.15)';
  deleteButton.addEventListener('click', () => removeEntry(entry));

  actions.append(previewButton, deleteButton);
  header.append(titleInput, actions);

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
    case 'number':
      controls.appendChild(numberInput(entry, field, value));
      break;
    case 'boolean':
      controls.appendChild(booleanSelect(entry, field, value));
      break;
    case 'library':
    case 'card-type':
    case 'style':
    case 'choice':
    case 'font-case':
      controls.appendChild(optionSelect(entry, field, value));
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
      controls.appendChild(mapEditor(entry, field, value, 'Key', 'Value'));
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
  return input;
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
  const choices = field.choices || [];
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

function hideSeasonsSelect(entry, field, value) {
  const select = document.createElement('select');
  ['true', 'false', 'auto'].forEach((option) => {
    const opt = document.createElement('option');
    opt.value = option;
    opt.textContent = option;
    if (String(value).toLowerCase() === option) {
      opt.selected = true;
    }
    select.appendChild(opt);
  });
  select.addEventListener('change', (event) => {
    const selected = event.target.value;
    if (selected === 'true') {
      updateField(entry, field, true);
    } else if (selected === 'false') {
      updateField(entry, field, false);
    } else {
      updateField(entry, field, 'auto');
    }
  });
  return select;
}

function translationEditor(entry, field, value) {
  const container = document.createElement('div');
  container.className = 'multi-row';

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
      row.className = 'multi-row-item';

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
      remove.textContent = '×';
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

  const browse = document.createElement('button');
  browse.textContent = 'Browse';
  browse.addEventListener('click', () => openFontBrowser(entry, field, input));

  wrapper.append(input, browse);
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
      line.className = 'table-list-row';

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
      remove.textContent = '×';
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

function mapEditor(entry, field, value, keyLabel, valueLabel, onUpdate) {
  const container = document.createElement('div');
  container.className = 'table-list';

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
      line.className = 'table-list-row';

      const keyInput = document.createElement('input');
      keyInput.type = 'text';
      keyInput.placeholder = keyLabel;
      keyInput.value = row.key;
      keyInput.addEventListener('input', (event) => {
        row.key = event.target.value;
        update();
      });

      const valueInput = document.createElement('input');
      valueInput.type = 'text';
      valueInput.placeholder = valueLabel;
      valueInput.value = row.value ?? '';
      valueInput.addEventListener('input', (event) => {
        row.value = event.target.value;
        update();
      });

      const remove = document.createElement('button');
      remove.textContent = '×';
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
      rows.push({ key: '', value: '' });
      renderRows();
    });
    list.appendChild(add);
  };

  renderRows();
  container.appendChild(list);
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
function openFieldSelector(entry) {
  const modal = buildModal('Add field');

  const available = state.fields.filter(
    (field) => getValue(entry.config, field.path) === undefined
  );

  if (available.length === 0) {
    const message = document.createElement('p');
    message.textContent = 'All available options are already configured.';
    modal.content.appendChild(message);
  } else {
    const list = document.createElement('div');
    list.className = 'search-results';

    available.forEach((field) => {
      const item = document.createElement('div');
      item.className = 'search-result';
      const title = document.createElement('div');
      title.innerHTML = `<h3>${field.label}</h3>`;
      const add = document.createElement('button');
      add.textContent = 'Add';
      add.addEventListener('click', () => {
        const defaultValue = defaultValueForField(field);
        updateField(entry, field, defaultValue);
        closeModal(modal.element);
        renderEntries();
      });
      item.append(title, add);
      list.appendChild(item);
    });

    modal.content.appendChild(list);
  }

  modal.footer.appendChild(closeButton(() => closeModal(modal.element)));
}

function openFontBrowser(entry, field, input) {
  const modal = buildModal('Select font');

  let currentPath = input.value || state.fontDirectory;

  const pathDisplay = document.createElement('p');
  pathDisplay.className = 'helper-text';
  modal.content.appendChild(pathDisplay);

  const browser = document.createElement('div');
  browser.className = 'font-browser';

  const directories = document.createElement('div');
  directories.className = 'panel';
  const files = document.createElement('div');
  files.className = 'panel';

  browser.append(directories, files);
  modal.content.appendChild(browser);

  const loadPath = async (path) => {
    const response = await fetch(`/api/fonts?path=${encodeURIComponent(path)}`);
    if (!response.ok) {
      showToast('Unable to load fonts', 'error');
      return;
    }
    const data = await response.json();
    currentPath = data.path;
    pathDisplay.textContent = data.path;

    directories.innerHTML = '<strong>Folders</strong>';
    files.innerHTML = '<strong>Fonts</strong>';

    const dirList = document.createElement('ul');
    const fileList = document.createElement('ul');

    const parent = PathParent(data.path);
    if (parent) {
      const up = document.createElement('li');
      up.textContent = '⬆︎ Parent directory';
      up.addEventListener('click', () => loadPath(parent));
      dirList.appendChild(up);
    }

    (data.entries || []).forEach((fileEntry) => {
      const item = document.createElement('li');
      item.textContent = fileEntry.name;
      if (fileEntry.type === 'directory') {
        item.addEventListener('click', () => loadPath(fileEntry.path));
        dirList.appendChild(item);
      } else {
        item.addEventListener('click', () => {
          input.value = fileEntry.path;
          updateField(entry, field, fileEntry.path);
          closeModal(modal.element);
        });
        fileList.appendChild(item);
      }
    });

    directories.appendChild(dirList);
    files.appendChild(fileList);
  };

  loadPath(currentPath);

  modal.footer.appendChild(closeButton(() => closeModal(modal.element)));
}

function PathParent(path) {
  if (!path) return null;
  const parts = path.split('/').filter(Boolean);
  if (parts.length === 0) return null;
  parts.pop();
  return `/${parts.join('/')}`;
}

function openPreview(entry) {
  const modal = buildModal('Generating preview');
  const message = document.createElement('p');
  message.textContent = 'Creating preview, please wait...';
  modal.content.appendChild(message);

  fetch('/api/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: entry.name, config: entry.config }),
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

    state.entries.push({
      id: `${name}-${Date.now()}`,
      name,
      config,
    });

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
async function saveConfiguration() {
  try {
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
  } catch (error) {
    showToast(error.message, 'error');
  }
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

  return { element: backdrop, content, footer };
}

function closeButton(onClick) {
  const button = document.createElement('button');
  button.textContent = 'Close';
  button.addEventListener('click', onClick);
  return button;
}

function closeModal(element) {
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

