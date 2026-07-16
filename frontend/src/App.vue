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
    primaryColor:         '#CD5B20',
    primaryColorHover:    '#D96F32',
    primaryColorPressed:  '#A94718',
    primaryColorSuppl:    '#CD5B20',
    infoColor:            '#0369A1',
    successColor:         '#047857',
    warningColor:         '#B45309',
    errorColor:           '#DC2626',
    borderRadius:         '6px',
    borderRadiusSmall:    '4px',
    fontFamily:           "'Fira Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif",
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
    colorPrimary:           '#CD5B20',
    colorHoverPrimary:      '#D96F32',
    colorPressedPrimary:    '#A94718',
    borderRadiusMedium:     '6px',
    borderRadiusSmall:      '4px',
    fontSizeMedium:         '13px',
    fontSizeSmall:          '12px',
    fontWeight:             '500',
  },
  Input: {
    borderRadius:           '6px',
    border:                 '1px solid #D3D9E0',
    borderHover:            '1px solid #CD5B20',
    borderFocus:            '1px solid #CD5B20',
    boxShadowFocus:         '0 0 0 3px rgba(205,91,32,0.12)',
    fontSizeMedium:         '13px',
  },
  Select: {
    peers: {
      InternalSelection: {
        borderRadius:    '6px',
        border:          '1px solid #D3D9E0',
        borderHover:     '1px solid #CD5B20',
        borderFocus:     '1px solid #CD5B20',
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
    headerTextColorProcess: '#CD5B20',
    splitorColorProcess:    '#CD5B20',
    indicatorTextColorProcess: '#fff',
    indicatorBorderColorProcess: '#CD5B20',
  },
}
</script>
