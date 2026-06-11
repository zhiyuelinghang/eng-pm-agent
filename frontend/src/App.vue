<template>
  <n-config-provider :theme-overrides="themeOverrides" :locale="zhCN" :date-locale="dateZhCN">
    <n-loading-bar-provider>
      <n-message-provider>
        <n-dialog-provider>
          <router-view />
        </n-dialog-provider>
      </n-message-provider>
    </n-loading-bar-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { zhCN, dateZhCN } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import { NConfigProvider, NLoadingBarProvider, NMessageProvider, NDialogProvider } from 'naive-ui'

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor:         '#E8590C',
    primaryColorHover:    '#F97316',
    primaryColorPressed:  '#C2410C',
    primaryColorSuppl:    '#E8590C',
    infoColor:            '#0369A1',
    successColor:         '#047857',
    warningColor:         '#B45309',
    errorColor:           '#DC2626',
    borderRadius:         '6px',
    borderRadiusSmall:    '4px',
    fontFamily:           "'Inter', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    fontFamilyMono:       "'JetBrains Mono', 'Fira Code', monospace",
    bodyColor:            '#F4F5F7',
    cardColor:            '#FFFFFF',
    modalColor:           '#FFFFFF',
    popoverColor:         '#FFFFFF',
    tableColor:           '#FFFFFF',
    tableColorHover:      '#F7F8FA',
    tableHeaderColor:     '#F7F8FA',
    tableColorStriped:    '#FAFBFC',
    dividerColor:         '#E5E8ED',
    borderColor:          '#D3D9E0',
    inputColor:           '#FFFFFF',
    inputColorDisabled:   '#F7F8FA',
    textColorBase:        '#1B2430',
    textColor1:           '#1B2430',
    textColor2:           '#5A6678',
    textColor3:           '#8792A2',
    placeholderColor:     '#A9B2BF',
    scrollbarColor:       'rgba(23,32,46,0.16)',
    scrollbarColorHover:  'rgba(23,32,46,0.3)',
    heightSmall:          '28px',
    heightMedium:         '34px',
    heightLarge:          '40px',
  },
  Button: {
    textColorPrimary:       '#fff',
    colorPrimary:           '#E8590C',
    colorHoverPrimary:      '#F97316',
    colorPressedPrimary:    '#C2410C',
    borderRadiusMedium:     '6px',
    borderRadiusSmall:      '4px',
    fontSizeMedium:         '13px',
    fontSizeSmall:          '12px',
    fontWeight:             '500',
  },
  Input: {
    borderRadius:           '6px',
    border:                 '1px solid #D3D9E0',
    borderHover:            '1px solid #E8590C',
    borderFocus:            '1px solid #E8590C',
    boxShadowFocus:         '0 0 0 3px rgba(232,89,12,0.12)',
    fontSizeMedium:         '13px',
  },
  Select: {
    peers: {
      InternalSelection: {
        borderRadius:    '6px',
        border:          '1px solid #D3D9E0',
        borderHover:     '1px solid #E8590C',
        borderFocus:     '1px solid #E8590C',
      },
      InternalSelectMenu: {
        borderRadius:    '8px',
      },
    },
  },
  DataTable: {
    borderRadius:          '10px',
    thColor:               '#F7F8FA',
    thTextColor:           '#8792A2',
    tdColorHover:          '#F7F8FA',
    borderColor:           '#E5E8ED',
    thFontWeight:          '600',
  },
  Dialog: {
    borderRadius:          '14px',
    padding:               '24px',
    titleFontSize:         '15px',
    titleFontWeight:       '700',
  },
  Card: {
    borderRadius:          '10px',
    border:                '1px solid #E5E8ED',
  },
  Drawer: {
    borderRadius:          '0',
  },
  Tag: {
    borderRadius:          '4px',
  },
  Steps: {
    headerTextColorProcess: '#E8590C',
    splitorColorProcess:    '#E8590C',
    indicatorColorProcess:  '#E8590C',
    indicatorTextColorProcess: '#fff',
    indicatorBorderColorProcess: '#E8590C',
  },
}
</script>
