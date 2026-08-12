import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      /* 4px grid spacing system */
      spacing: {
        "0.5": "2px",
        "1": "4px",
        "1.5": "6px",
        "2": "8px",
        "2.5": "10px",
        "3": "12px",
        "3.5": "14px",
        "4": "16px",
        "5": "20px",
        "6": "24px",
        "7": "28px",
        "8": "32px",
        "9": "36px",
        "10": "40px",
        "11": "44px",
        "12": "48px",
        "14": "56px",
        "16": "64px",
        "20": "80px",
        "24": "96px",
        "28": "112px",
        "32": "128px",
      },
      /* 8px max border-radius */
      borderRadius: {
        none: "0px",
        sm: "4px",
        DEFAULT: "6px",
        md: "8px",
        lg: "8px",
        xl: "8px",
        "2xl": "8px",
        "3xl": "8px",
        full: "9999px",
      },
      /* Inter / Geist Sans font stack */
      fontFamily: {
        sans: [
          "Inter",
          "Geist Sans",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "Geist Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
      /* Dark-first neutral palette with restrained accent */
      colors: {
        /* Mission Control color tokens */
        mission: {
          bg: '#0a0b0f',
          'surface-1': '#12141a',
          'surface-2': '#1a1d27',
          cyan: '#00d4ff',
          violet: '#7c3aed',
          emerald: '#10b981',
          crimson: '#ef4444',
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        /* Muted chart colors */
        chart: {
          raw: "hsl(var(--chart-raw))",
          predicted: "hsl(var(--chart-predicted))",
          corrected: "hsl(var(--chart-corrected))",
          grid: "hsl(var(--chart-grid))",
        },
        /* Semantic status colors */
        status: {
          healthy: "hsl(var(--status-healthy))",
          warning: "hsl(var(--status-warning))",
          critical: "hsl(var(--status-critical))",
          unknown: "hsl(var(--status-unknown))",
        },
      },
      /* 200ms max transitions with ease-out */
      transitionDuration: {
        DEFAULT: "200ms",
        "150": "150ms",
        "200": "200ms",
      },
      transitionTimingFunction: {
        DEFAULT: "ease-out",
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
      },
      animation: {
        "fade-in": "fade-in 200ms ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
export default config;
