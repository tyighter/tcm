# Option Rename Map

This table documents legacy option keys that are normalized to canonical keys in the Web UI/API and card rendering pipeline.

| Old key | New plain-English key | Meaning | Scope |
| --- | --- | --- | --- |
| `title_text` | `episode_title_text` (Episode title text) | Episode title string rendered on cards. | Global |
| `episode_text` | `episode_number_text` (Episode index text) | Season/episode index label text (for example, `EPISODE 5`). | Global |
| `title_text_format` | `episode_title_text_format` (Episode title format) | Formatting template for episode title text. | Global |
| `episode_text_format` | `episode_number_text_format` (Episode index format) | Formatting template for episode index text. | Global |
| `episode_text_case` | `episode_number_text_case` (Episode number case) | Character casing rules for episode index text. | Global |
| `episode_text_font` | `episode_number_text_font_file` (Episode number font file) | Font file for episode index text. | Global |
| `episode_text_font_size` | `episode_number_text_size` (Episode number text size) | Scale/size for episode index text. | Global |
| `episode_text_vertical_shift` | `episode_number_text_vertical_shift` (Episode number vertical shift) | Vertical offset for episode index text. | Global |
| `episode_text_stroke_color` | `episode_number_text_stroke_color` (Episode number stroke color) | Outline color for episode index text. | Global |
| `episode_stroke_color` | `episode_number_text_stroke_color` (Episode number stroke color) | Legacy alias for episode index outline color. | Global |
| `episode_text_stroke_width` | `episode_number_text_stroke_width` (Episode number stroke width) | Outline thickness for episode index text. | Global |
| `episode_title_stroke_color` | `episode_title_text_stroke_color` (Episode title stroke color) | Outline color for episode title text. | Global |
| `stroke_color` | `episode_title_text_stroke_color` (Episode title stroke color) | Legacy alias for episode title outline color. | Global |
| `episode_title_stroke_width` | `episode_title_text_stroke_width` (Episode title stroke width) | Outline thickness for episode title text. | Global |
| `title_text_margin` | `episode_title_text_horizontal_offset` (Episode title horizontal offset) | Horizontal offset for episode title text placement. | Global |
| `title_text_line_end_offset` | `episode_title_text_margin` (Episode title margin) | Right/line-end wrapping margin for episode title text. | Global |
| `font_file` | `episode_title_text_font_file` (Episode title font file) | Font file for episode title text. | Global |
| `font_size` | `episode_title_text_size` (Episode title size) | Scale/size for episode title text. | Global |
| `font_color` | `episode_title_text_color` (Episode title color) | Fill color for episode title text. | Global |
| `font_case` | `episode_title_text_case` (Episode title case) | Character casing rules for episode title text. | Global |
| `font_vertical_shift` | `episode_title_text_vertical_shift` (Episode title vertical shift) | Vertical offset for episode title text. | Global |
| `font_interline_spacing` | `episode_title_text_line_spacing` (Episode title line spacing) | Line spacing for wrapped episode title text. | Global |
| `font_interword_spacing` | `episode_title_text_word_spacing` (Episode title word spacing) | Word spacing for episode title text. | Global |
| `font_kerning` | `episode_title_text_kerning` (Episode title kerning) | Character kerning for episode title text. | Global |
