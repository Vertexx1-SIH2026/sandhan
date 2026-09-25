/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/pages/**/*.{js,jsx}",
    "./src/components/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#0B1F3A",        // deep case-file navy -- primary surface
        graphite: "#12213B",   // panel background, one step lighter than ink
        slate: {
          150: "#E7ECF3",
        },
        signal: "#E0A22A",     // amber -- alerts / pending HITL actions
        verified: "#2FA88A",   // teal-green -- confirmed / verified
        alertred: "#C4562F",   // burnt terracotta-red -- high-priority flags
      },
      fontFamily: {
        display: ["'IBM Plex Sans'", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
