class Field {
  constructor(objName, blockId, conditions) {
    this.obj = blockId ? $(`#${objName}${blockId}`) : $(`#${objName}`)
    this.objName = objName
    this.blockId = blockId
    this.conditions = conditions
  }
  get value() {
    return this.obj.val()
  }
  set value(val) {
    this.obj.val(val).trigger('change')
  }
}

class NumericalField extends Field {
  get value() {
    return Number(this.obj.val())
  }
  set value(val) {
    super.value = val
  }
}

class CheckField extends Field {
  get value() {
    return this.obj.is(":checked")
  }
  set value(val) {
    this.obj.prop('checked', val).trigger('change')
  }
}

class MultiSelectField extends Field {
  get value() {
    return super.value
  }
  set value(values) {
    if (!values) {
      return
    }
    let that = this
    values.forEach((v) => {
      that.obj.children('option').each(function (i) {
        if (this.value === v) {
          this.selected = true
        }
      })
    })
    that.obj.bsMultiSelect("UpdateData")
    that.obj.trigger('change')
  }
}

class Cameras {
  get value() {
    let a = []
    $("#cams-checkboxes input").each(function (e) {
      if (this.checked && !this.disabled) {
        a.push(this.value)
      }
    });
    return a.join(',')
  }

  set value(cameras) {
    $("#cams-checkboxes input").each(function (e) {
      this.checked = cameras.includes(this.value)
    });
  }
}

//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

class FieldObject {
  constructor(objName, objClass, conditions = {}) {
    this.objName = objName
    this.objClass = objClass
    this.conditions = conditions
  }

  getField(blockId = null) {
    return new this.objClass(this.objName, blockId, this.conditions)
  }
}

const AllFields = {
  get values() {
    let params = Object.keys(mainFields).reduce((obj, x) => {
      obj[x] = mainFields[x].getField().value
      return obj
    }, {})
    params['blocks'] = Blocks.values
    return params
  },
  set values(fieldsValues) {
    for (const [name, value] of Object.entries(fieldsValues)) {
      if (name === 'blocks') {
        Blocks.values = value
      } else {
        let obj = mainFields[name]
        if (!obj) {
          continue
        }
        obj.getField().value = value
      }
    }
  }
}

const Blocks = {
  get values() {
    let blocks = []
    const numBlocks = mainFields.num_blocks.getField().value
    for (let i = 1; i <= numBlocks; i++) {
      blocks.push(new Block(i).values)
    }
    return blocks
  },
  set values(blocksValues) {
    mainFields.num_blocks.getField().value = blocksValues.length
    for (let i = 1; i <= blocksValues.length; i++) {
      let block = new Block(i)
      block.values = blocksValues[i - 1]
    }
  }
}

class Block {
  constructor(idx) {
    this.idx = idx
    this.blockType = blockFields.main.block_type.getField(this.idx).value
    this.relevantObjFields = {}
    Object.assign(this.relevantObjFields, blockFields.main)
    Object.assign(this.relevantObjFields, blockFields[this.blockType])
  }

  isConditionOk(field) {
    for (const [objName, condition] of Object.entries(field.conditions)) {
        if (!this.relevantObjFields[objName]) {
          continue
        }
        let value = this.relevantObjFields[objName].getField(this.idx).value
        if (Array.isArray(condition)) {
          if (!condition.includes(value)) {
            return false
          }
        } else if (condition !== value) {
          return false
        }
      }
    return true
  }

  getFields(isCheckCondition=true) {
    const fields = Object.keys(this.relevantObjFields).reduce((obj, x) => {
      let field = this.relevantObjFields[x].getField(this.idx)
      if (this.isConditionOk(field) || !isCheckCondition) {
        obj[x] = field
      }
      return obj
    }, {})
    return fields
  }

  get values() {
    let block = {}
    let fields = this.getFields()
    for (const [name, field] of Object.entries(fields)) {
      block[name] = field.value
      if (name === 'reward_bugs' && !field.value) {
        block[name] = fields.bug_types.value
      }
    }
    return block
  }

  set values(blockValues) {
    const fields = this.getFields(false)
    for (const [name, value] of Object.entries(blockValues)) {
      let field = fields[name]
      if (!!field) {
        field.value = value
      }
    }
  }
}

//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

const mainFields = {
  name: new FieldObject('experimentName', Field),
  animal_id: new FieldObject('animalId', Field),
  is_use_predictions: new FieldObject('use_predictions', CheckField),
  time_between_blocks: new FieldObject('timeBetweenBlocks', NumericalField),
  extra_time_recording: new FieldObject('extraTimeRecording', NumericalField),
  cameras: new FieldObject('cameras', Cameras),
  num_blocks: new FieldObject('numBlocks', NumericalField)
}

const blockFields = {
  main: {
    num_trials: new FieldObject('experimentNumTrials', NumericalField),
    trial_duration: new FieldObject('experimentTrialDuration', NumericalField),
    iti: new FieldObject('experimentITI', NumericalField),
    block_type: new FieldObject('blockTypeSelect', Field)
  },
  bugs: {
    reward_type: new FieldObject('rewardTypeSelect', Field),
    bug_types: new FieldObject('bugTypeSelect', MultiSelectField),
    reward_bugs: new FieldObject('rewardBugSelect', MultiSelectField, {}),
    bug_speed: new FieldObject('bugSpeed', NumericalField),
    movement_type: new FieldObject('movementTypeSelect', Field),
    time_between_bugs: new FieldObject('timeBetweenBugs', NumericalField),
    is_anticlockwise: new FieldObject('isAntiClockWise', CheckField, {movement_type: 'circle'}),
    target_drift: new FieldObject('targetDriftSelect', Field, {movement_type: ['circle', 'low_horizontal', 'low_horizontal_noise']}),
    bug_height: new FieldObject('bugHeight', NumericalField, {movement_type: ['low_horizontal', 'low_horizontal_noise']}),
    is_default_bug_size: new FieldObject('isDefaultBugSize', CheckField),
    bug_size: new FieldObject('bugSize', NumericalField, {is_default_bug_size: false}),
    background_color: new FieldObject('backgroundColor', Field)
  },
  media: {
    media_url: new FieldObject('media-url', Field)
  }
}
