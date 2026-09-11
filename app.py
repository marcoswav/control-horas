def actualizar_fila_en_sheet(fecha_fec, nueva_hora):
  """Actualiza una fecha específica de forma segura sin borrar el resto de celdas"""
  try:
    filas = worksheet.get_all_values()
    # Forzar la fecha con una comilla simple al inicio (') evita que Google Sheets
    # la interprete mal y la convierta en fechas extrañas como 30/12/99.
    fecha_como_texto = f"'{fecha_fec}"

    if not filas:
      worksheet.append_row(
          ["Fecha", "Horas"], value_input_option="USER_ENTERED"
      )
      worksheet.append_row(
          [fecha_como_texto, float(nueva_hora)], value_input_option="USER_ENTERED"
      )
      return True

    encontrado = False
    for i, fila in enumerate(filas[1:], start=2):
      if fila and limpiar_fecha(fila[0]) == fecha_fec:
        # Actualizamos la celda de la fecha como texto estricto y las horas
        worksheet.update_cell(
            i, 1, fecha_como_texto, value_input_option="USER_ENTERED"
        )
        worksheet.update_cell(i, 2, float(nueva_hora))
        encontrado = True
        break

    if not encontrado:
      worksheet.append_row(
          [fecha_como_texto, float(nueva_hora)], value_input_option="USER_ENTERED"
      )

    return True
  except Exception as e:
    st.error(f"Error al actualizar la hoja: {e}")
    return False
