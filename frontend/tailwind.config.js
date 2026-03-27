/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,jsx,ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: '#FF4208', // AUMOVIO Orange
        'primary-hover': '#DA3806', // Orange 500 (Darker for hover)
        'primary-foreground': '#ffffff',
        secondary: '#4827AF', // AUMOVIO Purple
        'secondary-hover': '#341C7D', // Purple 500
        'secondary-foreground': '#ffffff',
        
        // Brand palette
        brand: {
          orange: {
            DEFAULT: '#FF4208',
            600: '#DA3806',
            500: '#FF4208',
            400: '#FF693B',
            300: '#FF906E',
            200: '#FFB7A1',
            100: '#FFF0EB',
            50: '#FFF7F5',
            text: '#FF4208', 
          },
          purple: {
            DEFAULT: '#4827AF',
            600: '#341C7D',
            500: '#4827AF',
            400: '#5C37D2',
            300: '#7E60DC',
            200: '#A08AE5',
            100: '#E8E0F7',
            50: '#F5F2FC',
            text: '#4827AF',
          },
          spark: '#FF850B',
        },

        background: '#ffffff',
        foreground: '#0f172a',
        muted: '#f1f5f9',
        'muted-foreground': '#64748b',
        border: '#e2e8f0',
        input: '#e2e8f0',
        success: '#22c55e',
        warning: '#f59e0b',
        error: '#ef4444',
      },
      borderRadius: {
        base: '0.5rem',
      },
      spacing: {
        sidebar: '280px',
        header: '64px',
      },
    },
  },
  plugins: [],
}

