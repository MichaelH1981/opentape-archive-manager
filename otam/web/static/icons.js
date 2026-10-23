const paths = {
  dashboard: "M3 3h7v7H3z M14 3h7v4h-7z M14 11h7v10h-7z M3 14h7v7H3z",
  calendar: "M4 5h16v16H4z M8 3v4 M16 3v4 M4 11h16 M8 15h2 M14 15h2",
  layers: "m12 3 9 5-9 5-9-5 9-5z M3 12l9 5 9-5 M3 16l9 5 9-5",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  search: "M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13z M16 16l5 5",
  tape: "M4 5h16a2 2 0 0 1 2 2v12H2V7a2 2 0 0 1 2-2z M7 10a3 3 0 1 0 0 6 3 3 0 0 0 0-6z M17 10a3 3 0 1 0 0 6 3 3 0 0 0 0-6z M7 16h10",
  restore: "M4 8v5h5 M5 12a8 8 0 1 0 3-7 M12 8v5l3 2",
  shield: "m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3z m-4 9 3 3 5-6",
  sync: "M20 7v5h-5 M4 17v-5h5 M5 8a8 8 0 0 1 13-3l2 3 M19 16a8 8 0 0 1-13 3l-2-3",
  server:
    "M4 3h16v7H4z M4 14h16v7H4z M7 6.5h.1 M7 17.5h.1 M11 6.5h6 M11 17.5h6",
  list: "M8 5h13 M8 12h13 M8 19h13 M3 5h.1 M3 12h.1 M3 19h.1",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M10 3h4l1 3 3 1 3 3v4l-3 1-1 3-3 3h-4l-1-3-3-1-3-3v-4l3-1 1-3z",
  home: "m3 11 9-8 9 8 M5 10v11h5v-7h4v7h5V10",
  logout: "M9 4H4v16h5 M10 12h11 m-5-5 5 5-5 5",
  menu: "M3 6h18 M3 12h18 M3 18h18",
  plus: "M12 5v14 M5 12h14",
  arrow: "M4 12h16 m-6-6 6 6-6 6",
  file: "M5 3h9l5 5v13H5z M14 3v6h5 M8 13h8 M8 17h5",
  check: "m5 12 4 4L19 6",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
  download: "M12 3v12 m-5-5 5 5 5-5 M4 16v5h16v-5",
  folder: "M3 6h7l2 3h9v12H3z",
  info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 11v6 M12 7h.1",
  filter: "M3 5h18l-7 8v6l-4 2v-8z",
  archive: "M3 3h18v5H3z M5 8v13h14V8 M10 12h4",
  cloud: "M6 17a5 5 0 0 1 0-10 7 7 0 0 1 13 2 4 4 0 0 1-1 8z",
  close: "M5 5l14 14 M5 19 19 5",
  external: "M14 3h7v7 M21 3 11 13 M10 3H3v18h18v-7",
};
const icon = (name) =>
  `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.file}"/></svg>`;

export { icon };
